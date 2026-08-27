from __future__ import annotations

import unittest
from dataclasses import replace

from tater_sat1_standalone.config import LedConfig
from tater_sat1_standalone.leds import BLACK, LedPhase, LedSnapshot, LedState, Sat1LedRenderer


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

    def test_pipeline_events_select_the_esp32_voice_phases(self) -> None:
        self.connect()
        expected = {
            "wake_word_detected": LedPhase.WAITING,
            "listening": LedPhase.LISTENING,
            "thinking": LedPhase.THINKING,
            "tts_speaking": LedPhase.REPLYING,
        }
        for event, phase in expected.items():
            with self.subTest(event=event):
                self.state.apply_event(event)
                self.assertEqual(self.state.snapshot(now=1).phase, phase)

        self.state.apply_event("tts_finished")
        self.assertEqual(self.state.snapshot(now=1).phase, LedPhase.IDLE)

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


if __name__ == "__main__":
    unittest.main()
