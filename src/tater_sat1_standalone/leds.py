from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import random
import sys
import threading
import time
from array import array
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from .config import DEFAULT_CONFIG_PATH, LedConfig, load_config

LOGGER = logging.getLogger("tater-sat1-leds")
RGB = tuple[int, int, int]
BLACK: RGB = (0, 0, 0)
RED: RGB = (255, 0, 0)
WARM_WHITE: RGB = (255, 227, 181)
LIGHT_OBJECT_ID = "led_ring"


class LedPhase(str, Enum):
    INITIALIZING = "initializing"
    DISCONNECTED = "disconnected"
    IDLE = "idle"
    WAITING = "waiting"
    LISTENING = "listening"
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    REPLYING = "replying"
    ERROR = "error"
    MUTED = "muted"
    VOLUME = "volume"
    TIMER_TICKING = "timer_ticking"
    TIMER_RINGING = "timer_ringing"


@dataclass(frozen=True)
class LedSnapshot:
    phase: LedPhase
    mic_muted: bool
    volume_muted: bool
    volume: float
    timer_total_seconds: int
    timer_seconds_left: int
    light_is_on: bool
    brightness: float
    red: float
    green: float
    blue: float
    doa_led_index: int | None = None
    doa_confidence: int = 0
    voice_direction_led: int = 12
    playback_level: float = 0.0
    listening_animation: str = "sat1_spinner"
    thinking_animation: str = "sat1_thinking"
    tool_call_animation: str = "ping_pong"
    replying_animation: str = "sat1_replying"


@dataclass(frozen=True)
class LedFrame:
    pixels: tuple[RGB, ...]
    interval: float


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, float(value)))


def _number(value: Any, default: float) -> float:
    if isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _integer(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def scale_color(color: RGB, factor: float) -> RGB:
    amount = _clamp(factor)
    return (
        int(color[0] * amount),
        int(color[1] * amount),
        int(color[2] * amount),
    )


def pcm_s16le_level(data: bytes) -> float:
    """Return the ESP speaker component's normalized PCM peak level."""
    usable = len(data) - (len(data) % 2)
    if usable <= 0:
        return 0.0
    samples = array("h")
    samples.frombytes(data[:usable])
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        return 0.0
    peak = max(abs(sample) for sample in samples)
    return _clamp(peak / 32767.0)


class LedState:
    """Thread-safe translation from Linux Satellite events to SAT1 LED priority state."""

    def __init__(self, config: LedConfig) -> None:
        self._lock = threading.Lock()
        self._ever_lva_connected = False
        self._lva_connected = False
        self._ha_connected = False
        self._pipeline_phase = "idle"
        self._last_event = ""
        self._mic_muted = False
        self._volume_muted = False
        self._volume = 1.0
        self._timer_active = False
        self._timer_ringing = False
        self._timer_total_seconds = 0
        self._timer_seconds_left = 0
        self._timer_received_at = 0.0
        self._error_until = 0.0
        self._volume_until = 0.0
        self._light_is_on = False
        self._brightness = config.brightness
        self._red = config.red
        self._green = config.green
        self._blue = config.blue
        self._doa_led_index: int | None = None
        self._doa_confidence = 0
        self._doa_valid_until = 0.0
        self._voice_direction_led = config.pixel_count // 2
        self._direction_scores = [0.0] * config.pixel_count
        self._doa_sample_at = 0.0
        self._playback_level = 0.0
        self._reply_playback_peak = 0.0
        self._listening_animation = "sat1_spinner"
        self._thinking_animation = "sat1_thinking"
        self._tool_call_animation = "ping_pong"
        self._replying_animation = "sat1_replying"

    def set_lva_connected(self, connected: bool) -> None:
        with self._lock:
            self._lva_connected = bool(connected)
            self._ever_lva_connected = self._ever_lva_connected or bool(connected)
            if not connected:
                self._ha_connected = False
                # Listening/thinking/replying are transient states owned by
                # the LVA process. They cannot survive its disconnection. On
                # reconnect, an actually active state is replayed immediately
                # after the snapshot by the peripheral API.
                self._pipeline_phase = "idle"

    def apply_event(self, event: str, data: Mapping[str, Any] | None = None, *, now: float | None = None) -> None:
        payload = data or {}
        timestamp = time.monotonic() if now is None else now
        with self._lock:
            previous_pipeline_phase = self._pipeline_phase

            if event == "snapshot":
                self._mic_muted = bool(payload.get("muted", False))
                self._volume = _clamp(_number(payload.get("volume"), 1.0))
                self._ha_connected = bool(payload.get("ha_connected", False))
                self._apply_settings(payload.get("settings"))
            elif event in {"wake_word_detected", "listening", "thinking", "tool_call", "tts_speaking"}:
                if event == "wake_word_detected" and previous_pipeline_phase not in {
                    "wake_word_detected",
                    "listening",
                }:
                    self._direction_scores = [0.0] * len(self._direction_scores)
                    self._doa_sample_at = 0.0
                if event == "thinking" and previous_pipeline_phase in {"wake_word_detected", "listening"}:
                    LOGGER.info("SAT1 captured voice direction at LED %d", self._voice_direction_led)
                if event == "tts_speaking":
                    self._reply_playback_peak = 0.0
                self._pipeline_phase = event
            elif event == "settings":
                self._apply_settings(payload.get("settings", payload))
            elif event == "pipeline_error" or event == "error":
                if event != "error" or str(payload.get("reason") or "") != "ha_disconnected":
                    self._pipeline_phase = "error"
                    self._error_until = timestamp + 2.0
                else:
                    self._ha_connected = False
            elif event == "tts_finished":
                if previous_pipeline_phase == "tts_speaking":
                    LOGGER.info("SAT1 reply PCM peak level: %.3f", self._reply_playback_peak)
                self._pipeline_phase = "idle"
            elif event == "idle":
                self._pipeline_phase = "idle"
                timer_was_cancelled = (
                    self._last_event in {"timer_ticking", "timer_updated"} and previous_pipeline_phase == "idle"
                )
                if self._timer_ringing or timer_was_cancelled:
                    self._clear_timer()
            elif event == "muted":
                self._mic_muted = bool(payload.get("muted", True))
            elif event == "volume_muted":
                self._volume_muted = bool(payload.get("muted", False))
            elif event == "volume_changed":
                self._volume = _clamp(_number(payload.get("volume"), self._volume))
                self._volume_until = timestamp + 2.0
            elif event in {"timer_ticking", "timer_updated", "timer_ringing"}:
                self._timer_active = True
                self._timer_ringing = event == "timer_ringing"
                self._timer_total_seconds = max(0, _integer(payload.get("total_seconds"), 0))
                self._timer_seconds_left = max(0, _integer(payload.get("seconds_left"), 0))
                self._timer_received_at = timestamp
            elif event == "disconnected":
                self._ha_connected = False
                self._pipeline_phase = "idle"
            elif event == "zeroconf":
                status = str(payload.get("status") or "")
                if status == "connected":
                    self._ha_connected = True
                elif status == "getting_started":
                    self._ha_connected = False
            elif event == "light_command" and str(payload.get("object_id") or "") == LIGHT_OBJECT_ID:
                self._light_is_on = bool(payload.get("state", True))
                self._brightness = _clamp(_number(payload.get("brightness"), self._brightness))
                self._red = _clamp(_number(payload.get("red"), self._red))
                self._green = _clamp(_number(payload.get("green"), self._green))
                self._blue = _clamp(_number(payload.get("blue"), self._blue))

            self._last_event = event

    def apply_doa(
        self,
        led_index: int,
        confidence: int,
        *,
        valid: bool,
        now: float | None = None,
    ) -> None:
        """Remember the latest reliable microphone direction for the listening ring."""
        timestamp = time.monotonic() if now is None else now
        if not valid:
            return
        with self._lock:
            self._doa_led_index = int(led_index) % 24
            self._doa_confidence = max(0, min(255, int(confidence)))
            # Brief invalid samples between words should not make the ring snap
            # back to centre. This matches the native SAT1 direction memory.
            self._doa_valid_until = timestamp + 1.0
            if self._doa_confidence < 1 or self._pipeline_phase not in {
                "wake_word_detected",
                "listening",
            }:
                return

            sample_seconds = timestamp - self._doa_sample_at if self._doa_sample_at else 0.05
            if sample_seconds <= 0.0 or sample_seconds > 0.20:
                sample_seconds = 0.05
            self._doa_sample_at = timestamp
            weight = sample_seconds * (1.0 + self._doa_confidence * 0.20)
            target = self._doa_led_index
            self._direction_scores[target] += weight
            self._direction_scores[(target + 1) % 24] += weight * 0.28
            self._direction_scores[(target - 1) % 24] += weight * 0.28
            self._voice_direction_led = max(range(24), key=self._direction_scores.__getitem__)

    def apply_playback_level(self, level: float) -> None:
        """Update the real speaker signal used by the replying voice ring."""
        with self._lock:
            self._playback_level = _clamp(level)
            if self._pipeline_phase == "tts_speaking":
                self._reply_playback_peak = max(self._reply_playback_peak, self._playback_level)

    def _apply_settings(self, raw: Any) -> None:
        if not isinstance(raw, Mapping):
            return
        self._brightness = _clamp(_number(raw.get("led_brightness"), self._brightness * 100.0) / 100.0)
        color = str(raw.get("led_color") or "").strip().lower().removeprefix("#")
        if len(color) == 3 and all(character in "0123456789abcdef" for character in color):
            color = "".join(character * 2 for character in color)
        if len(color) == 6 and all(character in "0123456789abcdef" for character in color):
            self._red = int(color[0:2], 16) / 255.0
            self._green = int(color[2:4], 16) / 255.0
            self._blue = int(color[4:6], 16) / 255.0
        self._listening_animation = str(
            raw.get("led_listening_animation") or self._listening_animation
        ).strip().lower()
        self._thinking_animation = str(raw.get("led_thinking_animation") or self._thinking_animation).strip().lower()
        self._tool_call_animation = str(raw.get("led_tool_call_animation") or self._tool_call_animation).strip().lower()
        self._replying_animation = str(raw.get("led_replying_animation") or self._replying_animation).strip().lower()

    def _clear_timer(self) -> None:
        self._timer_active = False
        self._timer_ringing = False
        self._timer_total_seconds = 0
        self._timer_seconds_left = 0
        self._timer_received_at = 0.0

    def snapshot(self, *, now: float | None = None) -> LedSnapshot:
        timestamp = time.monotonic() if now is None else now
        with self._lock:
            if not self._lva_connected:
                phase = LedPhase.DISCONNECTED if self._ever_lva_connected else LedPhase.INITIALIZING
            elif not self._ha_connected:
                phase = LedPhase.DISCONNECTED
            elif timestamp < self._volume_until:
                phase = LedPhase.VOLUME
            elif self._timer_ringing:
                phase = LedPhase.TIMER_RINGING
            elif self._pipeline_phase == "wake_word_detected":
                phase = LedPhase.WAITING
            elif self._pipeline_phase == "listening":
                phase = LedPhase.LISTENING
            elif self._pipeline_phase == "thinking":
                phase = LedPhase.THINKING
            elif self._pipeline_phase == "tool_call":
                phase = LedPhase.TOOL_CALL
            elif self._pipeline_phase == "tts_speaking":
                phase = LedPhase.REPLYING
            elif self._pipeline_phase == "error" and timestamp < self._error_until:
                phase = LedPhase.ERROR
            elif self._timer_active:
                phase = LedPhase.TIMER_TICKING
            elif self._mic_muted or self._volume_muted:
                phase = LedPhase.MUTED
            else:
                phase = LedPhase.IDLE

            seconds_left = self._timer_seconds_left
            if self._timer_active and not self._timer_ringing and self._timer_received_at:
                seconds_left = max(0, seconds_left - int(timestamp - self._timer_received_at))

            return LedSnapshot(
                phase=phase,
                mic_muted=self._mic_muted,
                volume_muted=self._volume_muted,
                volume=self._volume,
                timer_total_seconds=self._timer_total_seconds,
                timer_seconds_left=seconds_left,
                light_is_on=self._light_is_on,
                brightness=self._brightness,
                red=self._red,
                green=self._green,
                blue=self._blue,
                doa_led_index=self._doa_led_index if timestamp <= self._doa_valid_until else None,
                doa_confidence=self._doa_confidence if timestamp <= self._doa_valid_until else 0,
                voice_direction_led=self._voice_direction_led,
                playback_level=self._playback_level,
                listening_animation=self._listening_animation,
                thinking_animation=self._thinking_animation,
                tool_call_animation=self._tool_call_animation,
                replying_animation=self._replying_animation,
            )


class Sat1LedRenderer:
    """Render the SAT1 ESP32 firmware's effects for an even-sized LED ring."""

    def __init__(self, pixel_count: int = 24, *, random_value: Callable[[], float] = random.random) -> None:
        if pixel_count < 2 or pixel_count % 2:
            raise ValueError("SAT1 LED animations require an even pixel count of at least 2")
        self.pixel_count = pixel_count
        self._random_value = random_value
        self._phase: LedPhase | None = None
        self._index = 0
        self._pulse_step = 0
        self._pulse_decreasing = True
        self._twinkle = [0.0] * pixel_count
        self._animation_name = ""
        self._animation_tick = 0
        self._native_thinking_levels = [0.0] * pixel_count
        self._tool_forward = True
        self._tool_index = 0
        self._speaking_radius = 1.25
        self._directional_position = float(pixel_count // 2)

    def render(self, snapshot: LedSnapshot) -> LedFrame:
        animation_name = self._selected_animation(snapshot)
        continuing_directional = (
            self._phase in {LedPhase.WAITING, LedPhase.LISTENING}
            and snapshot.phase in {LedPhase.WAITING, LedPhase.LISTENING}
            and animation_name == self._animation_name
        )
        if (snapshot.phase != self._phase and not continuing_directional) or animation_name != self._animation_name:
            self._phase = snapshot.phase
            self._animation_name = animation_name
            self._index = 0
            self._pulse_step = 0
            self._pulse_decreasing = True
            self._twinkle = [self._random_value() for _ in range(self.pixel_count)]
            self._animation_tick = 0
            self._native_thinking_levels = [0.0] * self.pixel_count
            self._tool_forward = True
            self._tool_index = 0
            self._speaking_radius = 1.25
            self._directional_position = float(
                snapshot.doa_led_index if snapshot.doa_led_index is not None else self.pixel_count // 2
            )

        phase = snapshot.phase
        if phase == LedPhase.INITIALIZING:
            return LedFrame(tuple([scale_color(WARM_WHITE, 0.33)] * self.pixel_count), 0.1)
        if phase == LedPhase.DISCONNECTED:
            return LedFrame(self._twinkle_frame(scale_color(RED, 0.66)), 0.05)
        if phase == LedPhase.IDLE:
            color = scale_color(self._user_color(snapshot), snapshot.brightness)
            return LedFrame(tuple([color if snapshot.light_is_on else BLACK] * self.pixel_count), 0.1)
        if phase == LedPhase.WAITING:
            if snapshot.listening_animation == "sat1_spinner":
                return LedFrame(self._spin_frame(self._active_color(snapshot), reverse=False), 0.1)
            return self._native_animation_frame(snapshot.listening_animation, "directional", snapshot, 0.05)
        if phase == LedPhase.LISTENING:
            if snapshot.listening_animation == "sat1_spinner":
                return LedFrame(self._spin_frame(self._active_color(snapshot), reverse=False), 0.05)
            return self._native_animation_frame(snapshot.listening_animation, "directional", snapshot, 0.05)
        if phase == LedPhase.THINKING:
            if snapshot.thinking_animation == "sat1_thinking":
                return LedFrame(self._thinking_frame(self._active_color(snapshot)), 0.01)
            return self._native_animation_frame(snapshot.thinking_animation, "sparkle", snapshot, 0.08)
        if phase == LedPhase.TOOL_CALL:
            return self._native_animation_frame(snapshot.tool_call_animation, "ping_pong", snapshot, 0.08)
        if phase == LedPhase.REPLYING:
            if snapshot.replying_animation == "sat1_replying":
                return LedFrame(self._spin_frame(self._active_color(snapshot), reverse=True), 0.05)
            return self._native_animation_frame(snapshot.replying_animation, "voice_ring", snapshot, 0.04)
        if phase == LedPhase.ERROR:
            factor = self._next_pulse_factor()
            pixels = tuple([scale_color(RED, factor * self._raised_brightness(snapshot))] * self.pixel_count)
            return LedFrame(pixels, 0.01)
        if phase == LedPhase.MUTED:
            return LedFrame(self._muted_frame(snapshot), 0.016)
        if phase == LedPhase.VOLUME:
            return LedFrame(self._volume_frame(snapshot), 0.05)
        if phase == LedPhase.TIMER_RINGING:
            return LedFrame(self._timer_ring_frame(snapshot), 0.01)
        if phase == LedPhase.TIMER_TICKING:
            return LedFrame(self._timer_tick_frame(snapshot), 0.1)
        return LedFrame(tuple([BLACK] * self.pixel_count), 0.1)

    @staticmethod
    def _selected_animation(snapshot: LedSnapshot) -> str:
        if snapshot.phase in {LedPhase.WAITING, LedPhase.LISTENING}:
            return snapshot.listening_animation
        if snapshot.phase == LedPhase.THINKING:
            return snapshot.thinking_animation
        if snapshot.phase == LedPhase.TOOL_CALL:
            return snapshot.tool_call_animation
        if snapshot.phase == LedPhase.REPLYING:
            return snapshot.replying_animation
        return ""

    @staticmethod
    def _user_color(snapshot: LedSnapshot) -> RGB:
        return (
            int(_clamp(snapshot.red) * 255),
            int(_clamp(snapshot.green) * 255),
            int(_clamp(snapshot.blue) * 255),
        )

    def _active_color(self, snapshot: LedSnapshot) -> RGB:
        return scale_color(self._user_color(snapshot), max(snapshot.brightness, 0.2))

    @staticmethod
    def _raised_brightness(snapshot: LedSnapshot) -> float:
        return min(max(snapshot.brightness, 0.2) + 0.1, 1.0)

    def _twinkle_frame(self, color: RGB) -> tuple[RGB, ...]:
        pixels: list[RGB] = []
        for index in range(self.pixel_count):
            if self._random_value() < 0.5:
                self._twinkle[index] = 1.0
            else:
                self._twinkle[index] *= 0.85
            pixels.append(scale_color(color, self._twinkle[index]))
        return tuple(pixels)

    def _spin_frame(self, color: RGB, *, reverse: bool) -> tuple[RGB, ...]:
        pixels = [BLACK] * self.pixel_count
        half = self.pixel_count // 2
        if reverse:
            self._index = (self.pixel_count + self._index - 1) % self.pixel_count
            offsets = (
                (0, 1.0),
                (1, 192 / 255),
                (2, 128 / 255),
                (half, 1.0),
                (half + 1, 192 / 255),
                (half + 2, 128 / 255),
            )
        else:
            offsets = (
                (0, 1.0),
                (-1, 192 / 255),
                (-2, 128 / 255),
                (half, 1.0),
                (half - 1, 192 / 255),
                (half - 2, 128 / 255),
            )
        for offset, factor in offsets:
            pixels[(self._index + offset) % self.pixel_count] = scale_color(color, factor)
        if not reverse:
            self._index = (self._index + 1) % self.pixel_count
        return tuple(pixels)

    def _next_pulse_factor(self, steps: int = 10) -> float:
        factor = (steps - self._pulse_step) / steps
        self._pulse_step += 1 if self._pulse_decreasing else -1
        if self._pulse_step <= 0 or self._pulse_step >= steps:
            self._pulse_decreasing = not self._pulse_decreasing
        return factor

    def _thinking_frame(self, color: RGB) -> tuple[RGB, ...]:
        pixels = [BLACK] * self.pixel_count
        pulsed = scale_color(color, self._next_pulse_factor())
        pixels[self._index] = pulsed
        pixels[(self._index + self.pixel_count // 2) % self.pixel_count] = pulsed
        return tuple(pixels)

    @staticmethod
    def _triangle_wave(tick: int, period: int) -> float:
        step = tick % period
        half = period // 2
        if step > half:
            step = period - step
        return _clamp(step / half if half else 1.0)

    def _ring_distance(self, first: float, second: float) -> float:
        distance = abs(first - second)
        return min(distance, self.pixel_count - distance)

    @staticmethod
    def _clamp_color(red: float, green: float, blue: float) -> RGB:
        return (
            int(max(0.0, min(255.0, red))),
            int(max(0.0, min(255.0, green))),
            int(max(0.0, min(255.0, blue))),
        )

    def _native_animation_frame(
        self,
        animation: str,
        fallback: str,
        snapshot: LedSnapshot,
        interval: float,
    ) -> LedFrame:
        name = animation.strip().lower().replace("-", "_")
        color = self._active_color(snapshot)
        tick = self._animation_tick
        renderers: dict[str, Callable[[], tuple[RGB, ...]]] = {
            "directional": lambda: self._native_directional(
                tick,
                color,
                snapshot.doa_led_index,
                snapshot.doa_confidence,
                max(snapshot.brightness, 0.2),
            ),
            "sparkle": lambda: self._native_sparkle(tick, color, max(snapshot.brightness, 0.2)),
            "ping_pong": lambda: self._native_ping_pong(color),
            "voice_ring": lambda: self._native_voice_ring(
                tick,
                color,
                snapshot.volume,
                snapshot.playback_level,
                snapshot.voice_direction_led,
                max(snapshot.brightness, 0.2),
                snapshot.volume_muted,
            ),
            "spinner": lambda: self._native_spinner(tick, color, fast=False),
            "orbit": lambda: self._native_spinner(tick, color, fast=True),
            "pulse": lambda: self._native_pulse(tick, color),
            "breathe": lambda: self._native_breathe(tick, color),
            "comet": lambda: self._native_comet(tick, color, dual=False),
            "dual_comet": lambda: self._native_comet(tick, color, dual=True),
            "scanner": lambda: self._native_scanner(tick, color),
            "ripple": lambda: self._native_ripple(tick, color),
            "heartbeat": lambda: self._native_heartbeat(tick, color),
            "theater": lambda: self._native_theater(tick, color),
            "wave": lambda: self._native_wave(tick, color),
            "shimmer": lambda: self._native_shimmer(tick, color),
            "twinkle": lambda: self._native_twinkle(tick, color),
            "equalizer": lambda: self._native_equalizer(tick, color),
            "solid": lambda: tuple([color] * self.pixel_count),
        }
        pixels = renderers.get(name, renderers[fallback])()
        self._animation_tick += 1
        return LedFrame(pixels, interval)

    def _native_directional(
        self,
        tick: int,
        color: RGB,
        doa_led_index: int | None,
        doa_confidence: int,
        brightness: float,
    ) -> tuple[RGB, ...]:
        """Render the ESP firmware's selected-color beam with a warm-white tip."""
        if doa_led_index is not None:
            target = float(doa_led_index % self.pixel_count)
            delta = target - self._directional_position
            if delta > self.pixel_count / 2:
                delta -= self.pixel_count
            elif delta < -(self.pixel_count / 2):
                delta += self.pixel_count
            self._directional_position = (self._directional_position + delta * 0.35) % self.pixel_count

        pixels: list[RGB] = []
        for index in range(self.pixel_count):
            distance = self._ring_distance(float(index), self._directional_position)
            base_level = 0.06
            beam_level = max(0.0, 1.0 - distance / 7.0) * 0.65
            center_level = max(0.0, 1.0 - distance / 2.4)
            color_level = base_level + beam_level
            pixels.append(
                self._clamp_color(
                    color[0] * color_level + 255.0 * center_level * brightness,
                    color[1] * color_level + 240.0 * center_level * brightness,
                    color[2] * color_level + 170.0 * center_level * brightness,
                )
            )
        return tuple(pixels)

    def _native_sparkle(self, tick: int, color: RGB, brightness: float) -> tuple[RGB, ...]:
        breath_step = tick % 18
        breath = breath_step if breath_step <= 9 else 18 - breath_step
        pixels: list[RGB] = []
        for index in range(self.pixel_count):
            target = 0.025 + breath * 0.006
            bit_phase = (index * 7 + tick * 5) % 29
            if bit_phase == 0:
                target += 0.86
            elif bit_phase in {1, 28}:
                target += 0.46
            calc_phase = (index * 5 + tick * 2) % 17
            if calc_phase in {0, 8}:
                target += 0.50
            elif calc_phase in {1, 9}:
                target += 0.24
            target = min(target, 1.0)
            alpha = 0.58 if target > self._native_thinking_levels[index] else 0.20
            self._native_thinking_levels[index] += (target - self._native_thinking_levels[index]) * alpha
            color_level = self._native_thinking_levels[index]
            white_level = max(0.0, color_level - 0.55) * 0.46
            pixels.append(
                self._clamp_color(
                    color[0] * color_level + 255 * white_level * brightness,
                    color[1] * color_level + 240 * white_level * brightness,
                    color[2] * color_level + 170 * white_level * brightness,
                )
            )
        return tuple(pixels)

    def _native_ping_pong(self, color: RGB) -> tuple[RGB, ...]:
        span = self.pixel_count // 2
        lead_a = self._tool_index % span
        lead_b = (self.pixel_count - 1 - lead_a) % self.pixel_count
        trail_a = (lead_a - 1 if self._tool_forward else lead_a + 1) % self.pixel_count
        trail_b = (lead_b + 1 if self._tool_forward else lead_b - 1) % self.pixel_count
        tail_a = (lead_a - 2 if self._tool_forward else lead_a + 2) % self.pixel_count
        tail_b = (lead_b + 2 if self._tool_forward else lead_b - 2) % self.pixel_count
        pixels: list[RGB] = []
        for index in range(self.pixel_count):
            if index in {lead_a, lead_b}:
                level = 1.0
            elif index in {trail_a, trail_b}:
                level = 192 / 255
            elif index in {tail_a, tail_b}:
                level = 128 / 255
            else:
                level = 0.0
            pixels.append(scale_color(color, level))
        if self._tool_forward:
            if self._tool_index >= span - 1:
                self._tool_index = span - 2 if span > 2 else 0
                self._tool_forward = False
            else:
                self._tool_index += 1
        elif self._tool_index <= 0:
            self._tool_index = 1
            self._tool_forward = True
        else:
            self._tool_index -= 1
        return tuple(pixels)

    def _native_spinner(self, tick: int, color: RGB, *, fast: bool) -> tuple[RGB, ...]:
        head = (tick if fast else tick // 2) % self.pixel_count
        half = self.pixel_count // 2
        positions = {
            head: 1.0,
            (head + half) % self.pixel_count: 1.0,
            (head - 1) % self.pixel_count: 192 / 255,
            (head + half - 1) % self.pixel_count: 192 / 255,
            (head - 2) % self.pixel_count: 128 / 255,
            (head + half - 2) % self.pixel_count: 128 / 255,
        }
        return tuple(scale_color(color, positions.get(index, 0.0)) for index in range(self.pixel_count))

    def _native_pulse(self, tick: int, color: RGB) -> tuple[RGB, ...]:
        step = tick % 24
        wave = step if step <= 12 else 24 - step
        return tuple([scale_color(color, 0.10 + wave / 12 * 0.82)] * self.pixel_count)

    def _native_breathe(self, tick: int, color: RGB) -> tuple[RGB, ...]:
        return tuple([scale_color(color, 0.08 + self._triangle_wave(tick, 34) * 0.84)] * self.pixel_count)

    def _native_comet(self, tick: int, color: RGB, *, dual: bool) -> tuple[RGB, ...]:
        head = tick % self.pixel_count
        second = (head + self.pixel_count // 2) % self.pixel_count

        def level(distance: int) -> float:
            return {0: 1.0, 1: 0.68, 2: 0.40, 3: 0.20, 4: 0.09}.get(distance, 0.015)

        pixels: list[RGB] = []
        for index in range(self.pixel_count):
            amount = level((head - index + self.pixel_count) % self.pixel_count)
            if dual:
                amount = max(amount, level((second - index + self.pixel_count) % self.pixel_count))
            pixels.append(scale_color(color, amount))
        return tuple(pixels)

    def _native_scanner(self, tick: int, color: RGB) -> tuple[RGB, ...]:
        period = (self.pixel_count - 1) * 2
        phase = tick % period
        head = phase if phase < self.pixel_count else period - phase
        levels = {0: 1.0, 1: 0.54, 2: 0.22}
        return tuple(
            scale_color(color, levels.get(int(self._ring_distance(index, head)), 0.025))
            for index in range(self.pixel_count)
        )

    def _native_ripple(self, tick: int, color: RGB) -> tuple[RGB, ...]:
        radius = self._triangle_wave(tick, 24) * self.pixel_count * 0.48
        center = self.pixel_count // 2
        return tuple(
            scale_color(color, 0.035 + _clamp(1.0 - abs(self._ring_distance(index, center) - radius) / 1.45) * 0.88)
            for index in range(self.pixel_count)
        )

    def _native_heartbeat(self, tick: int, color: RGB) -> tuple[RGB, ...]:
        phase = tick % 34
        pulse = 1.0 - phase / 5 if phase <= 4 else 0.72 * (1.0 - (phase - 8) / 4) if 8 <= phase <= 11 else 0.0
        level = 0.04 + pulse * 0.92
        return tuple(scale_color(color, level * (1.0 if index % 2 == 0 else 0.72)) for index in range(self.pixel_count))

    def _native_theater(self, tick: int, color: RGB) -> tuple[RGB, ...]:
        phase = tick % 6
        levels = {0: 1.0, 1: 0.48, 5: 0.24}
        return tuple(scale_color(color, levels.get((index + phase) % 6, 0.025)) for index in range(self.pixel_count))

    def _native_wave(self, tick: int, color: RGB) -> tuple[RGB, ...]:
        center = float((tick // 2) % self.pixel_count)
        cross_center = (center + 6.0) % self.pixel_count
        pixels = []
        for index in range(self.pixel_count):
            level = 0.05 + _clamp(1.0 - self._ring_distance(index, center) / 4.2) * 0.84
            level += _clamp(1.0 - self._ring_distance(index, cross_center) / 2.4) * 0.16
            pixels.append(scale_color(color, _clamp(level)))
        return tuple(pixels)

    def _native_shimmer(self, tick: int, color: RGB) -> tuple[RGB, ...]:
        breath = 0.08 + self._triangle_wave(tick, 28) * 0.18
        pixels = []
        for index in range(self.pixel_count):
            phase = (index * 17 + tick * 5) % 37
            level = (
                1.0
                if phase == 0
                else 0.46
                if phase <= 3 or phase >= 34
                else 0.28
                if (phase + index) % 11 == 0
                else breath
            )
            pixels.append(scale_color(color, level))
        return tuple(pixels)

    def _native_twinkle(self, tick: int, color: RGB) -> tuple[RGB, ...]:
        pixels = []
        for index in range(self.pixel_count):
            phase = (index * 7 + tick * 3) % 31
            level = 0.95 if phase == 0 else 0.48 if phase in {1, 30} else 0.20 if phase in {2, 29} else 0.04
            pixels.append(scale_color(color, level))
        return tuple(pixels)

    def _native_equalizer(self, tick: int, color: RGB) -> tuple[RGB, ...]:
        pixels = []
        for index in range(self.pixel_count):
            phase = (index * 5 + tick * 3) % 20
            phase = 20 - phase if phase > 10 else phase
            level = 0.05 + phase / 10 * 0.72
            if (index * 13 + tick) % 17 == 0:
                level = 1.0
            pixels.append(scale_color(color, _clamp(level)))
        return tuple(pixels)

    def _native_voice_ring(
        self,
        tick: int,
        color: RGB,
        volume: float,
        playback_level: float,
        voice_direction_led: int,
        brightness: float,
        volume_muted: bool,
    ) -> tuple[RGB, ...]:
        center = int(voice_direction_led) % self.pixel_count
        # Pulse's post-volume monitor normally peaks around 0.06-0.08 for spoken
        # replies on SAT1. Expand that useful range so ordinary syllables travel
        # far enough around the 24-pixel ring to be clearly expressive.
        audio_level = min(1.0, _clamp(playback_level) * 7.5)
        volume_level = _clamp(volume)
        if volume_muted:
            audio_level = 0.0
            volume_level = 0.0
        target_radius = min(9.0, 1.25 + audio_level * 7.0 + volume_level * 1.25)
        alpha = 0.50 if target_radius > self._speaking_radius else 0.22
        self._speaking_radius += (target_radius - self._speaking_radius) * alpha
        pixels = []
        for index in range(self.pixel_count):
            distance = int(self._ring_distance(index, center))
            level = self._speaking_radius - distance
            if level <= 0:
                pixels.append(BLACK)
                continue
            level = min(level, 1.0)
            ripple = 0.86 + 0.14 * ((tick + distance * 5) % 4) / 3.0
            color_level = (0.12 + level * 0.76) * ripple
            center_level = max(0.0, 1.0 - distance / 2.4) * 0.52
            pixels.append(
                self._clamp_color(
                    color[0] * color_level + 255.0 * center_level * brightness,
                    color[1] * color_level + 240.0 * center_level * brightness,
                    color[2] * color_level + 170.0 * center_level * brightness,
                )
            )
        return tuple(pixels)

    def _muted_frame(self, snapshot: LedSnapshot) -> tuple[RGB, ...]:
        brightness = self._raised_brightness(snapshot)
        base = scale_color(self._user_color(snapshot), brightness) if snapshot.light_is_on else BLACK
        pixels = [base] * self.pixel_count
        red = scale_color(RED, brightness)
        if snapshot.mic_muted:
            for position in (0, self.pixel_count // 4, self.pixel_count // 2, 3 * self.pixel_count // 4):
                pixels[(position - 1) % self.pixel_count] = BLACK
                pixels[position] = red
                pixels[(position + 1) % self.pixel_count] = BLACK
        if snapshot.volume_muted or snapshot.volume <= 0.0:
            segment = self.pixel_count // 4
            for start in range(0, self.pixel_count, segment):
                pixels[(start + 1) % self.pixel_count] = BLACK
                for offset in range(2, max(3, segment - 1)):
                    pixels[(start + offset) % self.pixel_count] = red
                pixels[(start + segment - 1) % self.pixel_count] = BLACK
        return tuple(pixels)

    def _volume_frame(self, snapshot: LedSnapshot) -> tuple[RGB, ...]:
        pixels = [BLACK] * self.pixel_count
        brightness = self._raised_brightness(snapshot)
        color = scale_color(self._user_color(snapshot), brightness)
        ratio = self.pixel_count * _clamp(snapshot.volume)
        for index in range(self.pixel_count):
            if index <= ratio:
                pixels[index] = scale_color(color, min(ratio - index, 1.0))
        if snapshot.volume <= 0.0:
            pixels[0] = scale_color(RED, brightness)
        return tuple(pixels)

    def _timer_ring_frame(self, snapshot: LedSnapshot) -> tuple[RGB, ...]:
        brightness = self._raised_brightness(snapshot)
        pulse = self._next_pulse_factor()
        pixels = [scale_color(self._user_color(snapshot), brightness * pulse)] * self.pixel_count
        if snapshot.mic_muted:
            red = scale_color(RED, brightness)
            pixels[self.pixel_count // 8] = red
            pixels[3 * self.pixel_count // 8] = red
        return tuple(pixels)

    def _timer_tick_frame(self, snapshot: LedSnapshot) -> tuple[RGB, ...]:
        brightness = self._raised_brightness(snapshot)
        color = scale_color(self._user_color(snapshot), brightness)
        total = max(snapshot.timer_total_seconds, 1)
        ratio = self.pixel_count * max(snapshot.timer_seconds_left, 0) / total
        last_led_on = max(0, math.ceil(ratio) - 1)
        pixels = [BLACK] * self.pixel_count
        for index in range(self.pixel_count):
            dip = 0.9 if index == self._index % self.pixel_count and index != last_led_on else 1.0
            if index <= ratio:
                pixels[index] = scale_color(color, min(dip * (ratio - index), dip))
        if snapshot.mic_muted:
            red = scale_color(RED, brightness)
            for position in (self.pixel_count // 8, 3 * self.pixel_count // 8):
                pixels[(position - 1) % self.pixel_count] = BLACK
                pixels[position] = red
                pixels[(position + 1) % self.pixel_count] = BLACK
        self._index = (self.pixel_count + self._index - 1) % self.pixel_count
        return tuple(pixels)


class PixelDriver(Protocol):
    def write(self, pixels: Sequence[RGB]) -> None: ...


class XmosPixelDriver:
    """Write the production SAT1 ring through the XMOS SPI control service."""

    _CONTROL_RESOURCE_ID = 1
    _CONTROL_READ_BIT = 0x80
    _PAYLOAD_AVAILABLE = 0x17
    _STATUS_REGISTER_LEN = 4
    _RESOURCE_ID = 200
    _WRITE_RAW_COMMAND = 0
    _DOA_RESOURCE_ID = 231
    _DOA_READ_STATE_COMMAND = _CONTROL_READ_BIT
    _DOA_PAYLOAD_LEN = 32
    _IGNORED_IN_DEVICE = 0x07

    def __init__(self, config: LedConfig) -> None:
        try:
            import spidev
        except ImportError as exc:
            raise RuntimeError("spidev is required for the SAT1 XMOS LED ring") from exc

        self._pixel_count = config.pixel_count
        self._spi = spidev.SpiDev()
        self._spi.open(config.spi_bus, config.spi_device)
        self._spi.max_speed_hz = config.spi_speed_hz
        self._spi.mode = 3
        self._spi.bits_per_word = 8
        self._lock = threading.Lock()
        # The Satellite1 reference driver clocks one zero byte after opening
        # SPI so the first real transfer starts on a device-control boundary.
        self._spi.xfer2(bytearray(1))
        LOGGER.info(
            "SAT1 LED ring ready: %d RGB pixels through XMOS on SPI %d.%d",
            config.pixel_count,
            config.spi_bus,
            config.spi_device,
        )

    def write(self, pixels: Sequence[RGB]) -> None:
        if len(pixels) != self._pixel_count:
            raise ValueError(f"expected {self._pixel_count} SAT1 pixels, got {len(pixels)}")
        payload = bytearray()
        # The XMOS LED service forwards bytes directly to the WS2812 ring,
        # whose native channel order is GRB even though renderers use RGB.
        for red, green, blue in pixels:
            payload.extend((green, red, blue))
        packet = bytearray((self._RESOURCE_ID, self._WRITE_RAW_COMMAND, len(payload)))
        packet.extend(payload)

        # Writes are one transaction. Only read commands need the second NOP
        # transfer that clocks their payload back. Sending a NOP after every
        # LED frame can leave an old animation displayed even after idle.
        with self._lock:
            self._transfer_when_ready(packet, operation="LED command")

    def read_input_a(self) -> int:
        """Return the XMOS input-A status byte used by SAT1 controls."""
        status_dummies = self._STATUS_REGISTER_LEN - 1
        packet = bytearray((0, 0, 0)) + bytearray(status_dummies)
        with self._lock:
            response = self._transfer_when_ready(packet, operation="GPIO status")
        if len(response) < 2 + self._STATUS_REGISTER_LEN:
            raise RuntimeError("SAT1 XMOS returned a short GPIO status")
        if response[0] != self._CONTROL_RESOURCE_ID or response[1] == self._PAYLOAD_AVAILABLE:
            raise RuntimeError("SAT1 XMOS returned an unexpected GPIO status")
        return int(response[3])

    def read_doa(self) -> tuple[int, int, bool]:
        """Return ``(LED index, confidence, valid)`` from the XMOS DoA service."""
        payload = self._read_payload(
            self._DOA_RESOURCE_ID,
            self._DOA_READ_STATE_COMMAND,
            self._DOA_PAYLOAD_LEN,
            operation="DoA state",
        )
        confidence = int(payload[2])
        flags = int(payload[3])
        four_mic = bool(flags & 0x02)
        valid = bool(flags & 0x01)
        if four_mic:
            led_index = int(payload[14]) % self._pixel_count
        else:
            sample_delay = int.from_bytes(payload[0:2], byteorder="little", signed=True)
            sample_delay = max(-4, min(4, sample_delay))
            led_index = (self._pixel_count // 2 + sample_delay * 2) % self._pixel_count
        return led_index, confidence, valid

    def _read_payload(self, resource_id: int, command: int, payload_len: int, *, operation: str) -> bytes:
        packet = bytearray((resource_id, command, payload_len + 1))
        packet.extend(bytearray(payload_len))
        with self._lock:
            self._transfer_when_ready(packet, operation=f"{operation} request")
            time.sleep(0.001)
            response = self._transfer_when_ready(bytearray(payload_len + 3), operation=f"{operation} response")
        if len(response) < payload_len + 1 or response[0] != 0:
            raise RuntimeError(f"SAT1 XMOS returned a malformed {operation} response")
        return bytes(response[1 : payload_len + 1])

    def _transfer_when_ready(self, packet: bytearray, *, operation: str) -> list[int]:
        for attempt in range(5):
            response = self._spi.xfer2(packet)
            if response and response[0] != self._IGNORED_IN_DEVICE:
                return response
            if attempt < 4:
                time.sleep(0.1)
        raise RuntimeError(f"SAT1 XMOS remained busy during {operation}")


class Sat1ButtonTracker:
    """Debounce the three SAT1 controls exposed in XMOS GPIO input A."""

    _VOLUME_UP_MASK = 1 << 0
    _VOLUME_DOWN_MASK = 1 << 2
    _MIC_MUTE_MASK = 1 << 3

    def __init__(self, debounce_samples: int = 2) -> None:
        self._debounce_samples = max(1, int(debounce_samples))
        self._stable: int | None = None
        self._candidate: int | None = None
        self._candidate_count = 0

    def update(self, raw: int) -> tuple[str, ...]:
        value = int(raw) & 0xFF
        if self._stable is None:
            self._stable = value
            self._candidate = value
            return ("mute_mic" if value & self._MIC_MUTE_MASK else "unmute_mic",)

        if value != self._candidate:
            self._candidate = value
            self._candidate_count = 1
            return ()
        self._candidate_count += 1
        if value == self._stable or self._candidate_count < self._debounce_samples:
            return ()

        previous = self._stable
        self._stable = value
        commands: list[str] = []
        if previous & self._VOLUME_UP_MASK and not value & self._VOLUME_UP_MASK:
            commands.append("volume_up")
        if previous & self._VOLUME_DOWN_MASK and not value & self._VOLUME_DOWN_MASK:
            commands.append("volume_down")
        if bool(previous & self._MIC_MUTE_MASK) != bool(value & self._MIC_MUTE_MASK):
            commands.append("mute_mic" if value & self._MIC_MUTE_MASK else "unmute_mic")
        return tuple(commands)


class Ws281xPixelDriver:
    """24-pixel GRB WS2812 output using the Raspberry Pi PWM/DMA driver."""

    def __init__(self, config: LedConfig) -> None:
        try:
            from rpi_ws281x import Color, PixelStrip, ws
        except ImportError as exc:
            raise RuntimeError("rpi-ws281x is required for the SAT1 LED ring") from exc
        self._color = Color
        self._strip = PixelStrip(
            config.pixel_count,
            config.gpio_pin,
            config.frequency_hz,
            config.dma_channel,
            config.invert,
            255,
            config.channel,
            ws.WS2811_STRIP_GRB,
        )
        self._strip.begin()
        LOGGER.info("SAT1 LED ring ready: %d GRB pixels on GPIO %d", config.pixel_count, config.gpio_pin)

    def write(self, pixels: Sequence[RGB]) -> None:
        for index, (red, green, blue) in enumerate(pixels):
            self._strip.setPixelColor(index, self._color(red, green, blue))
        self._strip.show()


class AnimationWorker:
    def __init__(self, state: LedState, renderer: Sat1LedRenderer, driver: PixelDriver) -> None:
        self._state = state
        self._renderer = renderer
        self._driver = driver
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="sat1-led-ring")
        self._logged_phase: LedPhase | None = None

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        try:
            self._driver.write([BLACK] * self._renderer.pixel_count)
        except Exception:  # noqa: BLE001 - shutdown must continue if the HAT is unavailable
            LOGGER.warning("Could not clear the SAT1 LED ring during shutdown", exc_info=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                snapshot = self._state.snapshot()
                if snapshot.phase != self._logged_phase:
                    LOGGER.info("SAT1 LED phase: %s", snapshot.phase.value)
                    self._logged_phase = snapshot.phase
                frame = self._renderer.render(snapshot)
                self._driver.write(frame.pixels)
                self._stop.wait(frame.interval)
            except Exception:  # noqa: BLE001 - transient SPI failures should recover without killing animations
                LOGGER.warning("SAT1 LED update failed; retrying", exc_info=True)
                self._stop.wait(0.5)


async def run_hardware_inputs(websocket: Any, driver: XmosPixelDriver, state: LedState) -> None:
    """Poll SAT1 controls and DoA without blocking LED animation writes."""
    buttons = Sat1ButtonTracker()
    doa_due = 0.0
    failures = 0
    while True:
        try:
            input_a = await asyncio.to_thread(driver.read_input_a)
            for command in buttons.update(input_a):
                await websocket.send(json.dumps({"command": command, "data": {}}))
                LOGGER.info("SAT1 control: %s", command)

            now = time.monotonic()
            if now >= doa_due:
                led_index, confidence, valid = await asyncio.to_thread(driver.read_doa)
                state.apply_doa(led_index, confidence, valid=valid, now=now)
                doa_due = now + 0.08
            failures = 0
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - hardware polling should recover in place
            failures += 1
            if failures == 1 or failures % 50 == 0:
                LOGGER.warning("SAT1 control/DoA poll failed (%s)", exc)
        await asyncio.sleep(0.025)


async def _stop_process(process: asyncio.subprocess.Process | None) -> None:
    if process is None or process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()


async def run_playback_level_monitor(
    state: LedState,
    *,
    source: str,
    pulse_server: str,
    pulse_home: Path,
) -> None:
    """Measure the real PulseAudio sink-monitor signal used for SAT1 replies."""
    while True:
        process: asyncio.subprocess.Process | None = None
        try:
            environment = dict(os.environ)
            environment["HOME"] = str(pulse_home)
            if pulse_server:
                environment["PULSE_SERVER"] = pulse_server
            process = await asyncio.create_subprocess_exec(
                "/usr/bin/parec",
                f"--device={source}",
                "--format=s16le",
                "--rate=16000",
                "--channels=1",
                "--latency-msec=20",
                "--raw",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=environment,
            )
            if process.stdout is None:
                raise RuntimeError("parec did not expose its PCM stream")
            announced = False
            smoothed_level = 0.0
            while True:
                chunk = await process.stdout.read(1280)
                if not chunk:
                    raise RuntimeError(f"parec stopped with status {await process.wait()}")
                if not announced:
                    LOGGER.info("Reply animation audio level ready from Pulse source %s", source)
                    announced = True
                target_level = pcm_s16le_level(chunk)
                alpha = 0.40 if target_level > smoothed_level else 0.16
                smoothed_level += (target_level - smoothed_level) * alpha
                state.apply_playback_level(smoothed_level)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - Pulse may restart independently
            LOGGER.warning("Reply audio level unavailable (%s); retrying in 2 seconds", exc)
        finally:
            state.apply_playback_level(0.0)
            await _stop_process(process)
        await asyncio.sleep(2.0)


async def run_peripheral_client(
    config: LedConfig,
    state: LedState,
    xmos_driver: XmosPixelDriver | None = None,
) -> None:
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError("websockets is required for the SAT1 LED controller") from exc

    uri = f"ws://{config.peripheral_host}:{config.peripheral_port}"
    while True:
        try:
            async with websockets.connect(uri, open_timeout=5, ping_interval=20, ping_timeout=20) as websocket:
                LOGGER.info("Connected to Linux Satellite peripheral events at %s", uri)
                state.set_lva_connected(True)
                hardware_task = (
                    asyncio.create_task(run_hardware_inputs(websocket, xmos_driver, state))
                    if xmos_driver is not None
                    else None
                )
                try:
                    async for raw in websocket:
                        try:
                            message = json.loads(raw)
                        except (json.JSONDecodeError, TypeError):
                            LOGGER.warning("Ignoring invalid peripheral message")
                            continue
                        if not isinstance(message, dict):
                            continue
                        event = str(message.get("event") or "")
                        data = message.get("data")
                        if event:
                            state.apply_event(event, data if isinstance(data, dict) else {})
                finally:
                    if hardware_task is not None:
                        hardware_task.cancel()
                        await asyncio.gather(hardware_task, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - connection errors must all trigger retry
            LOGGER.warning("Peripheral event connection failed (%s); retrying in 2 seconds", exc)
        finally:
            state.set_lva_connected(False)
        await asyncio.sleep(2.0)


async def run(
    config: LedConfig,
    *,
    pulse_server: str = "unix:/run/tater-sat1-audio/pulse/native",
    pulse_home: Path = Path("/var/lib/tater-sat1-standalone"),
) -> None:
    if not config.enabled:
        LOGGER.info("SAT1 LED controller is disabled in configuration")
        await asyncio.Event().wait()
        return

    state = LedState(config)
    driver: PixelDriver
    xmos_driver: XmosPixelDriver | None = None
    if config.backend == "xmos":
        xmos_driver = XmosPixelDriver(config)
        driver = xmos_driver
    else:
        driver = Ws281xPixelDriver(config)
    worker = AnimationWorker(state, Sat1LedRenderer(config.pixel_count), driver)
    worker.start()
    playback_task = asyncio.create_task(
        run_playback_level_monitor(
            state,
            source=config.playback_monitor,
            pulse_server=pulse_server,
            pulse_home=pulse_home,
        )
    )
    try:
        await run_peripheral_client(config, state, xmos_driver)
    finally:
        playback_task.cancel()
        await asyncio.gather(playback_task, return_exceptions=True)
        worker.stop()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Drive the SAT1 LED ring from Tater voice events")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config(args.config)
    try:
        asyncio.run(
            run(
                config.leds,
                pulse_server=config.satellite.pulse_server,
                pulse_home=config.runtime.state_dir,
            )
        )
    except KeyboardInterrupt:
        pass
    except RuntimeError as exc:
        LOGGER.error("%s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
