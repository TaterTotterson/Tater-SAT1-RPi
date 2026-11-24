from __future__ import annotations

import fcntl
import runpy
import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from tater_sat1_standalone.config import StandaloneConfig
from tater_sat1_standalone.setup_reset import ResetFeedback, SetupResetGesture, reset_setup
from tater_sat1_standalone.leds import LedState, run as run_leds, run_setup_button


class SetupResetGestureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gesture = SetupResetGesture()
        self.now = 10.0
        self.triggers = 0
        self.feedback = ResetFeedback()

    def hold(self, pressed: bool, duration: float) -> None:
        for _ in range(round(duration / 0.01)):
            self.now += 0.01
            self.feedback, trigger = self.gesture.update(pressed, self.now)
            self.triggers += int(trigger)

    def click(self) -> None:
        self.hold(True, 0.15)
        self.hold(False, 0.15)

    def arm(self) -> None:
        self.hold(False, 0.1)
        for _ in range(5):
            self.click()
        self.assertEqual(self.feedback.clicks, 5)
        self.assertEqual(self.triggers, 0)

    def test_five_clicks_then_sixth_hold_triggers_once(self) -> None:
        self.arm()
        self.hold(True, 4.9)
        self.assertEqual(self.triggers, 0)
        self.assertIsNotNone(self.feedback.remaining)
        self.hold(True, 0.3)
        self.assertEqual(self.triggers, 1)
        self.hold(True, 8)
        self.assertEqual(self.triggers, 1)
        self.hold(False, 0.1)
        self.assertEqual(self.feedback, ResetFeedback())

    def test_six_quick_clicks_do_not_reset(self) -> None:
        self.arm()
        self.click()
        self.hold(True, 6)
        self.assertEqual(self.triggers, 0)

    def test_plain_long_hold_and_button_held_at_boot_are_ignored(self) -> None:
        self.hold(True, 10)
        self.assertEqual(self.triggers, 0)
        self.hold(False, 0.1)
        self.hold(True, 10)
        self.assertEqual(self.triggers, 0)

    def test_click_and_arm_windows_expire(self) -> None:
        self.hold(False, 0.1)
        for _ in range(4):
            self.click()
        self.hold(False, 3.2)
        self.assertEqual(self.feedback, ResetFeedback())
        self.click()
        self.assertEqual(self.feedback.clicks, 1)
        self.gesture.cancel()
        self.arm()
        self.hold(False, 5.2)
        self.hold(True, 6)
        self.assertEqual(self.triggers, 0)

    def test_release_early_or_a_read_failure_cancels_the_hold(self) -> None:
        self.arm()
        self.hold(True, 3)
        self.hold(False, 0.1)
        self.hold(True, 6)
        self.assertEqual(self.triggers, 0)
        self.gesture.cancel()
        self.arm()
        self.hold(True, 4)
        self.gesture.cancel()
        self.hold(True, 6)
        self.assertEqual(self.triggers, 0)

    def test_bounce_and_long_clicks_do_not_arm(self) -> None:
        self.hold(False, 0.1)
        for _ in range(12):
            self.hold(True, 0.02)
            self.hold(False, 0.02)
        self.assertEqual(self.feedback.clicks, 0)
        for _ in range(5):
            self.hold(True, 0.8)
            self.hold(False, 0.1)
        self.hold(True, 6)
        self.assertEqual(self.triggers, 0)

    def test_missing_samples_do_not_count_as_a_continuous_hold(self) -> None:
        self.arm()
        self.hold(True, 2)
        self.now += 6
        feedback, triggered = self.gesture.update(True, self.now)
        self.assertFalse(triggered)
        self.assertEqual(feedback, ResetFeedback())
        self.hold(True, 6)
        self.assertEqual(self.triggers, 0)


class ActionButtonBootConfigTests(unittest.TestCase):
    def test_reserving_bcm7_is_idempotent_and_preserves_existing_config(self) -> None:
        script = Path(__file__).resolve().parents[1] / "script/configure-action-button"
        configure = runpy.run_path(str(script))["configure"]
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "config.txt"
            original = "dtparam=spi=on\ndtoverlay=satellite1-i2s\n[pi4]\nmax_framebuffers=2\n"
            config.write_text(original)
            self.assertTrue(configure(config))
            self.assertFalse(configure(config))
            result = config.read_text()
            self.assertTrue(result.startswith(original))
            self.assertEqual(result.count("dtoverlay=spi0-1cs"), 1)
            self.assertIn("\n[all]\n# SAT1 action button", result)


class SetupResetPersistenceTests(unittest.TestCase):
    def config(self, root: str, flavor: str = "satellite") -> StandaloneConfig:
        return StandaloneConfig.from_mapping({"runtime": {"state_dir": root, "flavor": flavor}})

    def runner(self) -> Mock:
        def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            output = ""
            if command[:3] == ["nmcli", "-g", "UUID"]:
                output = "wifi-imager\nwired\nwifi-portal\n"
            if command[:3] == ["nmcli", "-g", "connection.type"]:
                output = "802-3-ethernet\n" if command[-1] == "wired" else "802-11-wireless\n"
            return subprocess.CompletedProcess(command, 0, output, "")
        return Mock(side_effect=run)

    def test_reset_forgets_wifi_and_pairing_but_keeps_image_app_and_other_data(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            config = self.config(folder)
            runtime = config.runtime
            runtime.satellite_state_dir.mkdir()
            cleared = [runtime.token_path, runtime.server_url_path, runtime.satellite_name_path,
                       runtime.satellite_room_path, runtime.satellite_identity_path]
            preserved = [runtime.first_boot_marker_path, Path(folder) / "app-data", Path(folder) / "version",
                         runtime.satellite_state_dir / "preferences.json"]
            for path in cleared + preserved:
                path.write_text("existing")
            runner = self.runner()
            with patch("tater_sat1_standalone.setup_reset.os.sync"):
                reset_setup(config, runner=runner)
            self.assertTrue(all(not path.exists() for path in cleared))
            self.assertTrue(all(path.read_text() == "existing" for path in preserved))
            commands = [call.args[0] for call in runner.call_args_list]
            deleted = [command[-1] for command in commands if command[:3] == ["nmcli", "connection", "delete"]]
            self.assertEqual(deleted, ["wifi-imager", "wifi-portal"])
            stop = ["systemctl", "stop", "tater-sat1-provisioning.service", "tater-sat1-satellite.service"]
            self.assertIn(stop, commands)
            self.assertEqual(commands[-1], ["systemctl", "--no-block", "restart", "tater-sat1-provisioning.service"])

    def test_standalone_keeps_its_internal_token(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            config = self.config(folder, "standalone")
            config.runtime.token_path.write_text("internal-token")
            runner = self.runner()
            with patch("tater_sat1_standalone.setup_reset.os.sync"):
                reset_setup(config, runner=runner)
            self.assertEqual(config.runtime.token_path.read_text(), "internal-token")
            self.assertIn("tater-sat1-voice.service", runner.call_args_list[4].args[0])

    def test_update_in_progress_or_pending_blocks_reset_without_changes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            config = self.config(folder)
            updates = Path(folder) / "updates"
            updates.mkdir()
            runner = self.runner()
            with (updates / "update.lock").open("a+") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                with self.assertRaisesRegex(RuntimeError, "update"):
                    reset_setup(config, runner=runner)
            for name in ("health-pending.json", "pending.sat1-ota"):
                marker = updates / name
                marker.touch()
                with self.assertRaisesRegex(RuntimeError, "update"):
                    reset_setup(config, runner=runner)
                marker.unlink()
            runner.assert_not_called()

    def test_portal_is_restarted_if_deleting_a_profile_fails(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            runner = self.runner()
            original = runner.side_effect
            def fail_delete(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                if command[:3] == ["nmcli", "connection", "delete"]:
                    raise subprocess.CalledProcessError(1, command)
                return original(command, **kwargs)
            runner.side_effect = fail_delete
            with patch("tater_sat1_standalone.setup_reset.os.sync"), self.assertRaises(subprocess.CalledProcessError):
                reset_setup(self.config(folder), runner=runner)
            expected = ["systemctl", "--no-block", "restart", "tater-sat1-provisioning.service"]
            self.assertEqual(runner.call_args.args[0], expected)


class OfflineRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_button_polls_without_a_voice_websocket(self) -> None:
        config = StandaloneConfig()
        state = LedState(config.leds)
        button = Mock()
        button.read_pressed.side_effect = [False, False, asyncio.CancelledError()]
        with patch("tater_sat1_standalone.leds.ActionButtonInput", return_value=button):
            with self.assertRaises(asyncio.CancelledError):
                await run_setup_button(state, config)
        self.assertEqual(button.read_pressed.call_count, 3)
        button.close.assert_called_once()

    async def test_disabled_ring_still_runs_recovery(self) -> None:
        config = StandaloneConfig.from_mapping({"leds": {"enabled": False}})
        with patch("tater_sat1_standalone.leds.run_setup_button", new_callable=AsyncMock) as recovery:
            await run_leds(config.leds, appliance_config=config)
        recovery.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
