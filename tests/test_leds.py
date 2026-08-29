from __future__ import annotations

import asyncio
import struct
import sys
import tempfile
import types
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from tater_sat1_standalone.config import LedConfig
from tater_sat1_standalone.leds import (
    BLACK,
    LedPhase,
    LedSnapshot,
    LedState,
    Sat1ButtonTracker,
    Sat1LedRenderer,
    XmosPixelDriver,
    pcm_s16le_level,
    run_setup_state_monitor,
)


def snapshot(phase: LedPhase, **overrides: object) -> LedSnapshot:
    values = LedSnapshot(
        phase=phase,
        mic_muted=False,
        volume_muted=False,
        volume=1.0,
        timer_total_seconds=0,
        timer_seconds_left=0,
        light_is_on=False,
        brightness=1.0,
        red=1.0,
        green=1.0,
        blue=1.0,
    )
    return replace(values, **overrides)


class LedStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = LedState(LedConfig())

    def connect(self) -> None:
        self.state.set_lva_connected(True)
        self.state.apply_event("snapshot", {"ha_connected": True, "muted": False, "volume": 0.7})

    def test_startup_and_connection_states_match_sat1_readiness(self) -> None:
        self.assertEqual(self.state.snapshot(now=1).phase, LedPhase.INITIALIZING)
        self.connect()
        self.assertEqual(self.state.snapshot(now=1).phase, LedPhase.IDLE)
        self.state.apply_event("disconnected")
        self.assertEqual(self.state.snapshot(now=1).phase, LedPhase.DISCONNECTED)

    def test_provisioning_has_priority_until_the_hotspot_closes(self) -> None:
        self.connect()
        self.state.apply_event("thinking")
        self.state.set_provisioning(True)
        self.assertEqual(self.state.snapshot(now=1).phase, LedPhase.PROVISIONING)

        self.state.set_provisioning(False)
        self.assertEqual(self.state.snapshot(now=1).phase, LedPhase.THINKING)

    def test_pipeline_events_select_the_esp32_voice_phases(self) -> None:
        self.connect()
        expected = {
            "wake_word_detected": LedPhase.WAITING,
            "listening": LedPhase.LISTENING,
            "thinking": LedPhase.THINKING,
            "tool_call": LedPhase.TOOL_CALL,
            "tts_speaking": LedPhase.REPLYING,
        }
        for event, phase in expected.items():
            with self.subTest(event=event):
                self.state.apply_event(event)
                self.assertEqual(self.state.snapshot(now=1).phase, phase)

        self.state.apply_event("tts_finished")
        self.assertEqual(self.state.snapshot(now=1).phase, LedPhase.IDLE)

    def test_lva_reconnect_does_not_restore_a_stale_pipeline_animation(self) -> None:
        self.connect()
        self.state.apply_event("wake_word_detected")
        self.assertEqual(self.state.snapshot(now=1).phase, LedPhase.WAITING)

        self.state.set_lva_connected(False)
        self.state.set_lva_connected(True)
        self.state.apply_event("snapshot", {"ha_connected": True})

        self.assertEqual(self.state.snapshot(now=1).phase, LedPhase.IDLE)

    def test_tater_settings_change_color_brightness_and_phase_animations(self) -> None:
        self.connect()
        self.state.apply_event(
            "settings",
            {
                "settings": {
                    "led_brightness": 40,
                    "led_color": "#12abef",
                    "led_listening_animation": "comet",
                    "led_thinking_animation": "shimmer",
                    "led_tool_call_animation": "scanner",
                    "led_replying_animation": "equalizer",
                }
            },
        )
        self.state.apply_event("tool_call")
        current = self.state.snapshot(now=1)

        self.assertEqual(current.phase, LedPhase.TOOL_CALL)
        self.assertAlmostEqual(current.brightness, 0.4)
        self.assertAlmostEqual(current.red, 0x12 / 255)
        self.assertAlmostEqual(current.green, 0xAB / 255)
        self.assertAlmostEqual(current.blue, 0xEF / 255)
        self.assertEqual(current.listening_animation, "comet")
        self.assertEqual(current.thinking_animation, "shimmer")
        self.assertEqual(current.tool_call_animation, "scanner")
        self.assertEqual(current.replying_animation, "equalizer")

    def test_reconnect_snapshot_restores_persisted_tater_led_settings(self) -> None:
        self.state.set_lva_connected(True)
        self.state.apply_event(
            "snapshot",
            {
                "ha_connected": True,
                "settings": {
                    "led_brightness": 25,
                    "led_color": "#ff5a1f",
                    "led_listening_animation": "directional",
                },
            },
        )

        current = self.state.snapshot(now=1)
        self.assertAlmostEqual(current.brightness, 0.25)
        self.assertEqual(current.listening_animation, "directional")

    def test_recent_valid_doa_is_exposed_then_expires(self) -> None:
        self.connect()
        self.state.apply_doa(19, 6, valid=True, now=10)
        self.assertEqual(self.state.snapshot(now=10.5).doa_led_index, 19)
        self.assertEqual(self.state.snapshot(now=10.5).doa_confidence, 6)
        self.assertIsNone(self.state.snapshot(now=11.1).doa_led_index)

        self.state.apply_doa(3, 0, valid=False, now=12)
        self.assertIsNone(self.state.snapshot(now=12).doa_led_index)

    def test_listening_saves_dominant_direction_for_the_reply(self) -> None:
        self.connect()
        self.state.apply_event("wake_word_detected", now=10)
        for step in range(5):
            self.state.apply_doa(4, 5, valid=True, now=10.1 + step * 0.08)
        self.state.apply_event("thinking", now=11)
        self.state.apply_event("tts_speaking", now=12)

        current = self.state.snapshot(now=12)
        self.assertEqual(current.voice_direction_led, 4)
        self.assertIsNone(current.doa_led_index)

    def test_playback_level_is_exposed_to_reply_renderer(self) -> None:
        self.connect()
        self.state.apply_playback_level(0.18)
        self.assertAlmostEqual(self.state.snapshot(now=1).playback_level, 0.18)

    def test_esp32_priority_keeps_volume_above_timer_and_voice(self) -> None:
        self.connect()
        self.state.apply_event(
            "timer_ringing",
            {"total_seconds": 60, "seconds_left": 0},
            now=10,
        )
        self.state.apply_event("thinking", now=10)
        self.assertEqual(self.state.snapshot(now=10).phase, LedPhase.TIMER_RINGING)

        self.state.apply_event("volume_changed", {"volume": 0.5}, now=10)
        self.assertEqual(self.state.snapshot(now=11).phase, LedPhase.VOLUME)
        self.assertEqual(self.state.snapshot(now=13).phase, LedPhase.TIMER_RINGING)

    def test_timer_countdown_and_mute_fall_back_in_priority_order(self) -> None:
        self.connect()
        self.state.apply_event("muted", {"muted": True})
        self.state.apply_event(
            "timer_ticking",
            {"total_seconds": 60, "seconds_left": 30},
            now=10,
        )
        current = self.state.snapshot(now=12)
        self.assertEqual(current.phase, LedPhase.TIMER_TICKING)
        self.assertEqual(current.timer_seconds_left, 28)

        self.state.apply_event("idle", now=12)
        self.assertEqual(self.state.snapshot(now=12).phase, LedPhase.MUTED)


class LedRendererTests(unittest.TestCase):
    def setUp(self) -> None:
        self.renderer = Sat1LedRenderer(24, random_value=lambda: 0.0)

    @staticmethod
    def lit(frame: tuple[tuple[int, int, int], ...]) -> set[int]:
        return {index for index, color in enumerate(frame) if color != BLACK}

    def test_provisioning_matches_the_esp32_warm_white_twinkle(self) -> None:
        first = self.renderer.render(snapshot(LedPhase.PROVISIONING))
        second = self.renderer.render(snapshot(LedPhase.PROVISIONING))

        self.assertEqual(first.interval, 0.08)
        self.assertEqual(first.pixels[0], (242, 215, 171))
        self.assertEqual(first.pixels[1], (10, 9, 7))
        self.assertEqual(second.pixels[0], (10, 9, 7))
        self.assertEqual(second.pixels[4], (242, 215, 171))

    def test_waiting_uses_the_esp32_opposing_clockwise_comets(self) -> None:
        first = self.renderer.render(snapshot(LedPhase.WAITING))
        second = self.renderer.render(snapshot(LedPhase.WAITING))
        self.assertEqual(first.interval, 0.1)
        self.assertEqual(self.lit(first.pixels), {0, 10, 11, 12, 22, 23})
        self.assertEqual(self.lit(second.pixels), {0, 1, 11, 12, 13, 23})

    def test_listening_and_replying_use_the_esp32_speed_and_direction(self) -> None:
        listening = self.renderer.render(snapshot(LedPhase.LISTENING))
        replying = self.renderer.render(snapshot(LedPhase.REPLYING))
        self.assertEqual(listening.interval, 0.05)
        self.assertEqual(replying.interval, 0.05)
        self.assertEqual(self.lit(replying.pixels), {0, 1, 11, 12, 13, 23})

    def test_thinking_pulses_two_opposing_pixels(self) -> None:
        frame = self.renderer.render(snapshot(LedPhase.THINKING))
        self.assertEqual(frame.interval, 0.01)
        self.assertEqual(self.lit(frame.pixels), {0, 12})

    def test_muted_markers_match_the_four_esp32_ring_positions(self) -> None:
        frame = self.renderer.render(snapshot(LedPhase.MUTED, mic_muted=True))
        self.assertEqual(self.lit(frame.pixels), {0, 6, 12, 18})
        self.assertTrue(all(frame.pixels[index][0] > 0 for index in (0, 6, 12, 18)))

    def test_volume_and_timer_use_24_pixel_arcs(self) -> None:
        volume = self.renderer.render(snapshot(LedPhase.VOLUME, volume=0.5))
        timer = self.renderer.render(
            snapshot(
                LedPhase.TIMER_TICKING,
                timer_total_seconds=60,
                timer_seconds_left=30,
            )
        )
        self.assertEqual(self.lit(volume.pixels), set(range(12)))
        self.assertEqual(self.lit(timer.pixels), set(range(12)))
        self.assertEqual(len(volume.pixels), 24)
        self.assertEqual(len(timer.pixels), 24)

    def test_every_tater_native_animation_renders_on_the_sat1_ring(self) -> None:
        animations = {
            "directional",
            "sparkle",
            "ping_pong",
            "voice_ring",
            "spinner",
            "orbit",
            "pulse",
            "breathe",
            "comet",
            "dual_comet",
            "scanner",
            "ripple",
            "heartbeat",
            "theater",
            "wave",
            "shimmer",
            "twinkle",
            "equalizer",
            "solid",
        }
        for animation in animations:
            with self.subTest(animation=animation):
                renderer = Sat1LedRenderer(24, random_value=lambda: 0.0)
                frame = renderer.render(snapshot(LedPhase.LISTENING, listening_animation=animation))
                self.assertEqual(len(frame.pixels), 24)
                self.assertTrue(any(color != BLACK for color in frame.pixels))

    def test_tater_led_color_and_brightness_drive_selected_animation(self) -> None:
        frame = self.renderer.render(
            snapshot(
                LedPhase.LISTENING,
                listening_animation="solid",
                brightness=0.5,
                red=1.0,
                green=0.0,
                blue=0.0,
            )
        )

        self.assertEqual(set(frame.pixels), {(127, 0, 0)})
        self.assertEqual(frame.interval, 0.05)

    def test_directional_animation_moves_its_brightest_wedge_to_doa(self) -> None:
        frame = None
        for _ in range(8):
            frame = self.renderer.render(
                snapshot(
                    LedPhase.LISTENING,
                    listening_animation="directional",
                    doa_led_index=4,
                    doa_confidence=5,
                )
            )
        assert frame is not None
        brightest = max(range(24), key=lambda index: sum(frame.pixels[index]))
        self.assertIn(brightest, {3, 4, 5})
        self.assertGreater(sum(frame.pixels[brightest]), sum(frame.pixels[12]))

    def test_directional_tip_uses_the_esp_warm_white_highlight(self) -> None:
        frame = None
        for _ in range(8):
            frame = self.renderer.render(
                snapshot(
                    LedPhase.LISTENING,
                    listening_animation="directional",
                    doa_led_index=4,
                    doa_confidence=5,
                    red=1.0,
                    green=0.0,
                    blue=0.0,
                )
            )
        assert frame is not None
        brightest = max(range(24), key=lambda index: sum(frame.pixels[index]))
        self.assertIn(brightest, {3, 4, 5})
        self.assertGreater(frame.pixels[brightest][1], 180)
        self.assertGreater(frame.pixels[brightest][2], 120)

    def test_voice_ring_expands_with_audio_and_uses_saved_doa_center(self) -> None:
        quiet_renderer = Sat1LedRenderer(24, random_value=lambda: 0.0)
        loud_renderer = Sat1LedRenderer(24, random_value=lambda: 0.0)
        quiet = quiet_renderer.render(
            snapshot(
                LedPhase.REPLYING,
                replying_animation="voice_ring",
                playback_level=0.0,
                voice_direction_led=4,
            )
        )
        loud = loud_renderer.render(
            snapshot(
                LedPhase.REPLYING,
                replying_animation="voice_ring",
                playback_level=0.2,
                voice_direction_led=4,
            )
        )

        self.assertGreater(len(self.lit(loud.pixels)), len(self.lit(quiet.pixels)))
        self.assertEqual(sum(loud.pixels[4]), max(sum(pixel) for pixel in loud.pixels))

    def test_voice_ring_makes_normal_sat1_reply_levels_visibly_wider(self) -> None:
        quiet_renderer = Sat1LedRenderer(24, random_value=lambda: 0.0)
        reply_renderer = Sat1LedRenderer(24, random_value=lambda: 0.0)
        quiet_snapshot = snapshot(
            LedPhase.REPLYING,
            replying_animation="voice_ring",
            playback_level=0.0,
            voice_direction_led=4,
        )
        reply_snapshot = snapshot(
            LedPhase.REPLYING,
            replying_animation="voice_ring",
            playback_level=0.07,
            voice_direction_led=4,
        )

        for _ in range(3):
            quiet = quiet_renderer.render(quiet_snapshot)
            reply = reply_renderer.render(reply_snapshot)

        self.assertGreaterEqual(len(self.lit(reply.pixels)) - len(self.lit(quiet.pixels)), 6)

    def test_tool_call_heads_match_esp_mirrored_path(self) -> None:
        frame = self.renderer.render(
            snapshot(LedPhase.TOOL_CALL, tool_call_animation="ping_pong")
        )
        strongest = {index for index, pixel in enumerate(frame.pixels) if max(pixel) == 255}
        self.assertEqual(strongest, {0, 23})


class XmosPixelDriverTests(unittest.TestCase):
    def test_writes_grb_frame_through_sat1_xmos_control_resource(self) -> None:
        instances: list[object] = []

        class FakeSpi:
            def __init__(self) -> None:
                self.opened: tuple[int, int] | None = None
                self.transfers: list[bytes] = []
                instances.append(self)

            def open(self, bus: int, device: int) -> None:
                self.opened = (bus, device)

            def xfer2(self, packet: bytearray) -> list[int]:
                self.transfers.append(bytes(packet))
                if len(self.transfers) == 1:
                    return [1] * len(packet)
                return [1, 0, *([0] * (len(packet) - 2))]

        fake_module = types.SimpleNamespace(SpiDev=FakeSpi)
        with patch.dict(sys.modules, {"spidev": fake_module}):
            driver = XmosPixelDriver(LedConfig())
            pixels = [(1, 2, 3), *([(0, 0, 0)] * 23)]
            driver.write(pixels)

        spi = instances[0]
        self.assertEqual(spi.opened, (0, 0))
        self.assertEqual(spi.max_speed_hz, 1_000_000)
        self.assertEqual(spi.mode, 3)
        self.assertEqual(spi.bits_per_word, 8)
        self.assertEqual(spi.transfers[0], bytes(1))
        self.assertEqual(spi.transfers[1][:6], bytes((200, 0, 72, 2, 1, 3)))
        self.assertEqual(len(spi.transfers[1]), 75)
        self.assertEqual(len(spi.transfers), 2)

    def test_reads_gpio_status_and_doa_payload(self) -> None:
        instances: list[object] = []
        doa_payload = bytearray(32)
        doa_payload[2] = 5
        doa_payload[3] = 0x03
        doa_payload[14] = 19

        class FakeSpi:
            def __init__(self) -> None:
                self.transfers: list[bytes] = []
                instances.append(self)

            def open(self, _bus: int, _device: int) -> None:
                pass

            def xfer2(self, packet: bytearray) -> list[int]:
                self.transfers.append(bytes(packet))
                call = len(self.transfers)
                if call == 1:
                    return [1]
                if call == 2:
                    return [1, 0, 0, 7, 0, 0]
                if call == 3:
                    return [1, 0, *([0] * (len(packet) - 2))]
                return [0, *doa_payload, 0, 0]

        with patch.dict(sys.modules, {"spidev": types.SimpleNamespace(SpiDev=FakeSpi)}):
            driver = XmosPixelDriver(LedConfig())
            self.assertEqual(driver.read_input_a(), 7)
            self.assertEqual(driver.read_doa(), (19, 5, True))

        spi = instances[0]
        self.assertEqual(spi.transfers[2][:3], bytes((231, 0x80, 33)))
        self.assertEqual(spi.transfers[3], bytes(35))


class PlaybackLevelTests(unittest.TestCase):
    def test_pcm_level_tracks_silence_and_peak_signal(self) -> None:
        silence = struct.pack("<" + "h" * 320, *([0] * 320))
        signal = struct.pack("<" + "h" * 320, *([8192] * 320))
        spike = struct.pack("<" + "h" * 320, *([0] * 319 + [16384]))

        self.assertEqual(pcm_s16le_level(silence), 0.0)
        self.assertAlmostEqual(pcm_s16le_level(signal), 0.25, places=3)
        self.assertAlmostEqual(pcm_s16le_level(spike), 0.5, places=3)


class SetupStateMonitorTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_marker_controls_provisioning_phase(self) -> None:
        state = LedState(LedConfig())
        with tempfile.TemporaryDirectory() as temp_dir:
            active_path = Path(temp_dir) / "active"
            task = asyncio.create_task(
                run_setup_state_monitor(state, active_path=active_path, poll_interval=0.005)
            )
            try:
                await asyncio.sleep(0.02)
                self.assertEqual(state.snapshot(now=1).phase, LedPhase.INITIALIZING)

                active_path.touch()
                await asyncio.sleep(0.02)
                self.assertEqual(state.snapshot(now=1).phase, LedPhase.PROVISIONING)

                active_path.unlink()
                await asyncio.sleep(0.02)
                self.assertEqual(state.snapshot(now=1).phase, LedPhase.INITIALIZING)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


class Sat1ButtonTrackerTests(unittest.TestCase):
    def test_volume_buttons_fire_once_on_debounced_press(self) -> None:
        tracker = Sat1ButtonTracker()
        self.assertEqual(tracker.update(0b0111), ("unmute_mic",))
        self.assertEqual(tracker.update(0b0110), ())
        self.assertEqual(tracker.update(0b0110), ("volume_up",))
        self.assertEqual(tracker.update(0b0110), ())
        self.assertEqual(tracker.update(0b0111), ())
        self.assertEqual(tracker.update(0b0111), ())

    def test_volume_down_and_mute_switch_are_reported(self) -> None:
        tracker = Sat1ButtonTracker()
        tracker.update(0b0111)
        tracker.update(0b0011)
        self.assertEqual(tracker.update(0b0011), ("volume_down",))
        tracker.update(0b1011)
        self.assertEqual(tracker.update(0b1011), ("mute_mic",))


if __name__ == "__main__":
    unittest.main()
