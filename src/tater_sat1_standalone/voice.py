from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .ota import NativeOtaController


DEFAULT_VERSION_PATH = Path("/etc/tater-sat1-standalone/version")
DEFAULT_STATE_DIR = Path("/var/lib/tater-sat1-standalone")
DEFAULT_PUBLIC_KEY = Path("/etc/tater-sat1-standalone/update-public.pem")


def installed_version(path: Path = DEFAULT_VERSION_PATH) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        value = ""
    return value or "tater-sat1-development"


def ota_client_class() -> type[Any]:
    from linux_voice_assistant.tater_native import TaterNativeClient

    class Sat1TaterNativeClient(TaterNativeClient):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            version_path = Path(os.getenv("TATER_SAT1_VERSION_PATH", str(DEFAULT_VERSION_PATH)))
            kwargs["firmware_version"] = installed_version(version_path)
            super().__init__(*args, **kwargs)
            self.capabilities.update(
                {
                    "ota": True,
                    "ota_format": "tater_sat1_signed_bundle_v1",
                    "ota_rollback": True,
                }
            )
            state_dir = Path(os.getenv("TATER_SAT1_STATE_DIR", str(DEFAULT_STATE_DIR)))
            board = str(kwargs.get("board") or "").strip().lower()
            flavor = "satellite" if board == "satellite1_rpi_satellite" else "standalone"
            public_key = Path(os.getenv("TATER_SAT1_UPDATE_PUBLIC_KEY", str(DEFAULT_PUBLIC_KEY)))
            self._sat1_ota = NativeOtaController(self, state_dir, flavor, public_key)

        def _handle_message(self, body: dict[str, Any]) -> None:
            if self._sat1_ota.handle_message(body):
                return
            super()._handle_message(body)

        async def close(self) -> None:
            await self._sat1_ota.close()
            await super().close()

    return Sat1TaterNativeClient


def main() -> None:
    from linux_voice_assistant import __main__ as linux_voice_main

    linux_voice_main.TaterNativeClient = ota_client_class()
    linux_voice_main.run()
