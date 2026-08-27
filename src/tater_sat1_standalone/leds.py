from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import random
import threading
import time
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

    def set_lva_connected(self, connected: bool) -> None:
        with self._lock:
            self._lva_connected = bool(connected)
            self._ever_lva_connected = self._ever_lva_connected or bool(connected)
            if not connected:
                self._ha_connected = False

    def apply_event(self, event: str, data: Mapping[str, Any] | None = None, *, now: float | None = None) -> None:
        payload = data or {}
        timestamp = time.monotonic() if now is None else now
        with self._lock:
            previous_pipeline_phase = self._pipeline_phase

            if event == "snapshot":
                self._mic_muted = bool(payload.get("muted", False))
                self._volume = _clamp(_number(payload.get("volume"), 1.0))
                self._ha_connected = bool(payload.get("ha_connected", False))
            elif event in {"wake_word_detected", "listening", "thinking", "tts_speaking"}:
                self._pipeline_phase = event
            elif event == "pipeline_error" or event == "error":
                if event != "error" or str(payload.get("reason") or "") != "ha_disconnected":
                    self._pipeline_phase = "error"
                    self._error_until = timestamp + 2.0
                else:
                    self._ha_connected = False
            elif event == "tts_finished":
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

    def render(self, snapshot: LedSnapshot) -> LedFrame:
        if snapshot.phase != self._phase:
            self._phase = snapshot.phase
            self._index = 0
            self._pulse_step = 0
            self._pulse_decreasing = True
            self._twinkle = [self._random_value() for _ in range(self.pixel_count)]

        phase = snapshot.phase
        if phase == LedPhase.INITIALIZING:
            return LedFrame(tuple([scale_color(WARM_WHITE, 0.33)] * self.pixel_count), 0.1)
        if phase == LedPhase.DISCONNECTED:
            return LedFrame(self._twinkle_frame(scale_color(RED, 0.66)), 0.05)
        if phase == LedPhase.IDLE:
            color = scale_color(self._user_color(snapshot), snapshot.brightness)
            return LedFrame(tuple([color if snapshot.light_is_on else BLACK] * self.pixel_count), 0.1)
        if phase == LedPhase.WAITING:
            return LedFrame(self._spin_frame(self._active_color(snapshot), reverse=False), 0.1)
        if phase == LedPhase.LISTENING:
            return LedFrame(self._spin_frame(self._active_color(snapshot), reverse=False), 0.05)
        if phase == LedPhase.THINKING:
            return LedFrame(self._thinking_frame(self._active_color(snapshot)), 0.01)
        if phase == LedPhase.REPLYING:
            return LedFrame(self._spin_frame(self._active_color(snapshot), reverse=True), 0.05)
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

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        self._driver.write([BLACK] * self._renderer.pixel_count)

    def _run(self) -> None:
        while not self._stop.is_set():
            frame = self._renderer.render(self._state.snapshot())
            self._driver.write(frame.pixels)
            self._stop.wait(frame.interval)


async def run_peripheral_client(config: LedConfig, state: LedState) -> None:
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
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - connection errors must all trigger retry
            LOGGER.warning("Peripheral event connection failed (%s); retrying in 2 seconds", exc)
        finally:
            state.set_lva_connected(False)
        await asyncio.sleep(2.0)


async def run(config: LedConfig) -> None:
    if not config.enabled:
        LOGGER.info("SAT1 LED controller is disabled in configuration")
        await asyncio.Event().wait()
        return

    state = LedState(config)
    driver = Ws281xPixelDriver(config)
    worker = AnimationWorker(state, Sat1LedRenderer(config.pixel_count), driver)
    worker.start()
    try:
        await run_peripheral_client(config, state)
    finally:
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
        asyncio.run(run(config.leds))
    except KeyboardInterrupt:
        pass
    except RuntimeError as exc:
        LOGGER.error("%s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
