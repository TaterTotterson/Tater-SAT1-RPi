from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from tater_sat1_standalone.voice import ota_client_class


class _FakeNativeClient:
    def __init__(self, *args, **kwargs) -> None:
        del args
        self.capabilities = dict(kwargs.get("capabilities") or {})
        self.base_ble_pause = False

    def _ble_should_pause(self) -> bool:
        return self.base_ble_pause


class VoiceClientTests(unittest.TestCase):
    def test_ble_observer_pauses_for_ota_and_base_latency_guards(self) -> None:
        package = ModuleType("linux_voice_assistant")
        package.__path__ = []
        native = ModuleType("linux_voice_assistant.tater_native")
        native.TaterNativeClient = _FakeNativeClient

        with patch.dict(
            sys.modules,
            {
                "linux_voice_assistant": package,
                "linux_voice_assistant.tater_native": native,
            },
        ):
            client_class = ota_client_class()
            client = client_class(board="satellite1_rpi_standalone")

        self.assertFalse(client._ble_should_pause())
        client._sat1_ota.task = SimpleNamespace(done=lambda: False)
        self.assertTrue(client._ble_should_pause())
        client._sat1_ota.task = SimpleNamespace(done=lambda: True)
        self.assertFalse(client._ble_should_pause())
        client.base_ble_pause = True
        self.assertTrue(client._ble_should_pause())


if __name__ == "__main__":
    unittest.main()
