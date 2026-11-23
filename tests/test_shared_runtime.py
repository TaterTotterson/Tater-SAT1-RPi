"""Exercise the SAT1 adapter against the installed, pinned Linux runtime."""

import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tater_sat1_standalone.commands import build_satellite_plan
from tater_sat1_standalone.config import StandaloneConfig
from tater_sat1_standalone.voice import ota_client_class


AVAILABLE = (
    importlib.util.find_spec("linux_voice_assistant") is not None
    and importlib.util.find_spec("linux_voice_assistant.tater_native") is not None
)
if os.getenv("TATER_REQUIRE_SHARED_RUNTIME") == "1" and not AVAILABLE:
    raise RuntimeError("Install the pinned Linux Satellite runtime before running compatibility tests")


def satellite():
    def player():
        return SimpleNamespace(
            synchronized_controls_available=True,
            **{name: Mock() for name in (
                "prepare_synchronized", "synchronized_snapshot", "seek_synchronized",
                "jump_synchronized", "set_synchronized_speed", "reset_synchronized",
                "resume_synchronized", "resume", "stop", "duck",
            )},
        )

    state = SimpleNamespace(
        name="sat1-test", friendly_name="SAT1", version="test", volume=0.8,
        output_only=False, connected=False, native_settings={}, available_wake_words={},
        music_player=player(), tts_player=player(),
    )
    result = SimpleNamespace(
        state=state, send_messages=Mock(), handle_audio=Mock(), wakeup=Mock(),
        _emit=Mock(), connection_lost=Mock(), set_tts_segment_grace_seconds=Mock(),
    )
    state.satellite = result
    return result


@unittest.skipUnless(AVAILABLE, "pinned Linux runtime is tested in the shared-runtime CI job")
class SharedRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.root = Path(self.work.name)
        self.environment = patch.dict(os.environ, {
            "TATER_SAT1_STATE_DIR": str(self.root),
            "TATER_SAT1_VERSION_PATH": str(self.root / "version"),
        })
        self.environment.start()
        (self.root / "version").write_text("tater-sat1-satellite-test\n")
        self.device = satellite()
        self.client = ota_client_class()(
            self.device, url="http://127.0.0.1:8501", device_id="sat1-test",
            board="satellite1_rpi_satellite", identity_file=self.root / "identity.json",
        )
        # No Pulse server or actual music stream is running in these tests.
        self.client.sendspin.duck = Mock()

    async def asyncTearDown(self):
        await self.client.close()
        self.environment.stop()
        self.work.cleanup()

    async def test_shared_features_and_sat1_ota_are_available_together(self):
        capabilities = self.client.capabilities
        for name in (
            "identity_update", "nanowakeword", "openwakeword", "audio_scenes",
            "tts_overlays", "audio_ducking", "barge_in", "wake_during_playback", "status_led", "ota",
        ):
            self.assertTrue(capabilities[name], name)
        self.assertEqual(capabilities["wake_preroll_boundary"], 1)
        self.assertEqual(self.client.firmware_version, "tater-sat1-satellite-test")
        self.assertEqual(self.client._sat1_ota.flavor, "satellite")
        if os.getenv("TATER_REQUIRE_SHARED_RUNTIME") == "1":
            self.assertTrue(capabilities["sendspin_player"])
            self.assertTrue(capabilities["sendspin_output_channel_selection"])
        # Constructing a client must not start Bluetooth discovery.
        self.assertIsNone(self.client.features.bluetooth.backend)
        self.assertIsNone(self.client._bluetooth.backend)

    async def test_live_identity_reaches_the_next_sat1_launch(self):
        self.client._handle_message({
            "type": "identity.set", "id": "identity-test",
            "payload": {"device_name": "Kitchen SAT1", "room": "Kitchen"},
        })
        self.assertEqual((self.client.device_name, self.client.room), ("Kitchen SAT1", "Kitchen"))
        config = StandaloneConfig.from_mapping({"runtime": {"state_dir": str(self.root)}})
        config.runtime.satellite_state_dir.mkdir()
        config.runtime.satellite_identity_path.write_bytes((self.root / "identity.json").read_bytes())
        plan = build_satellite_plan(config)
        self.assertEqual(plan.command[plan.command.index("--name") + 1], "Kitchen SAT1")
        self.assertEqual(plan.command[plan.command.index("--tater-room") + 1], "Kitchen")

    async def test_appliance_ota_pauses_shared_discovery(self):
        proxy = self.client.features.bluetooth
        self.assertFalse(proxy.should_pause())
        self.client._sat1_ota.task = SimpleNamespace(done=lambda: False)
        self.assertTrue(proxy.should_pause())
        self.client._sat1_ota.task = None
        self.device._pipeline_active = True
        self.assertTrue(proxy.should_pause())

    async def test_bundled_boundary_model_runs(self):
        import linux_voice_assistant
        from linux_voice_assistant.wake_boundary import WakeBoundaryModel

        bundle = Path(linux_voice_assistant.__file__).parent / "assets/wake/hey_tater.wake-bundle.json"
        self.assertIn("wake_boundary", json.loads(bundle.read_text()))
        model = WakeBoundaryModel()
        try:
            model.estimate(bytes(16000 * 2), 8000, bundle)
            self.assertTrue(model.last_status.get("ready"), model.last_status)
        finally:
            model.close()
