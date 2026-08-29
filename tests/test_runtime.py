import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tater_sat1_standalone.commands import build_satellite_plan, build_tater_plan
from tater_sat1_standalone.config import StandaloneConfig
from tater_sat1_standalone.runtime import ensure_private_token, prepare_runtime
from tater_sat1_standalone.provisioning import provision_pairing


class RuntimeTests(unittest.TestCase):
    def test_private_token_is_stable_and_owner_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "state" / "token"
            first = ensure_private_token(path)
            second = ensure_private_token(path)
            self.assertEqual(first, second)
            self.assertGreaterEqual(len(first), 32)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_plans_share_loopback_and_token_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = StandaloneConfig.from_mapping(
                {
                    "runtime": {"state_dir": temp_dir},
                    "satellite": {"room": "Kitchen", "audio_output_device": "satellite1_output"},
                }
            )
            token = prepare_runtime(config.runtime)
            tater = build_tater_plan(config, token)
            satellite = build_satellite_plan(config)

            self.assertEqual(tater.environment["TATER_NATIVE_SATELLITE_TOKEN"], token)
            self.assertEqual(tater.environment["TATER_SETUP_PROFILE"], "edge")
            self.assertEqual(tater.environment["TATER_REMOTE_ONLY"], "1")
            self.assertEqual(
                tater.environment["TATER_SAT1_SELF_OTA_STATE_DIR"],
                str(config.runtime.state_dir / "updates"),
            )
            self.assertEqual(tater.environment["TATER_SETUP_REQUIRE_LOCAL_LLM"], "0")
            self.assertEqual(tater.environment["MALLOC_ARENA_MAX"], "2")
            self.assertEqual(tater.environment["VOICE_WEBRTC_VAD_AGGRESSIVENESS"], "3")
            self.assertEqual(tater.environment["VOICE_VAD_SILENCE_SECONDS"], "0.62")
            self.assertEqual(tater.environment["VOICE_CONTINUED_CHAT_REOPEN_TIMEOUT_SECONDS"], "8.0")
            self.assertEqual(
                tater.environment["VOICE_CONTINUED_CHAT_REOPEN_NO_SPEECH_TIMEOUT_S"],
                "3.0",
            )
            worker_limits = {
                name: value
                for name, value in tater.environment.items()
                if name.startswith("TATER_RUNTIME_") and name.endswith("_WORKERS")
            }
            self.assertEqual(set(worker_limits.values()), {"1"})
            self.assertEqual(len(worker_limits), 6)
            self.assertIn("http://127.0.0.1:8501", satellite.command)
            self.assertIn("pulse/satellite1_output", satellite.command)
            token_index = satellite.command.index("--tater-token-file") + 1
            self.assertEqual(satellite.command[token_index], str(config.runtime.token_path))
            self.assertIn("Kitchen", satellite.command)
            self.assertTrue(config.runtime.satellite_state_dir.is_dir())
            self.assertEqual(os.stat(config.runtime.state_dir).st_mode & 0o777, 0o700)

    def test_satellite_flavor_pairs_with_remote_tater_without_local_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = StandaloneConfig.from_mapping(
                {
                    "runtime": {"flavor": "satellite", "state_dir": temp_dir},
                    "tater": {"url": "http://main-tater.local:8501"},
                    "satellite": {"name": "auto", "device_id": "auto"},
                }
            )
            self.assertEqual(prepare_runtime(config.runtime), "")
            self.assertFalse(config.runtime.token_path.exists())
            with mock.patch("tater_sat1_standalone.identity.hardware_suffix", return_value="a1b2c3"):
                satellite = build_satellite_plan(config)
            self.assertIn("http://main-tater.local:8501", satellite.command)
            self.assertIn("tater-sat1-a1b2c3", satellite.command)

            url = provision_pairing(config, "123456")
            self.assertEqual(url, "http://main-tater.local:8501")
            self.assertEqual(config.runtime.token_path.read_text(encoding="utf-8").strip(), "123456")
            self.assertEqual(config.runtime.token_path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
