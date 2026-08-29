from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ReleaseManifestTests(unittest.TestCase):
    def test_manifest_publishes_each_flavor_as_connected_ota_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            release = Path(temporary)
            for flavor in ("standalone", "satellite"):
                (release / f"tater-sat1-{flavor}-v1.2.3-ota.sat1").write_bytes(flavor.encode("utf-8"))
            completed = subprocess.run(
                [
                    str(ROOT / "script/build_release_manifest.py"),
                    "--version",
                    "v1.2.3",
                    "--release-tag",
                    "v1.2.3",
                    "--release-dir",
                    str(release),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            manifest = json.loads((release / "tater-sat1-rpi-v1.2.3-manifest.json").read_text(encoding="utf-8"))
            devices = {row["board"]: row for row in manifest["devices"]}
            self.assertEqual(set(devices), {"satellite1_rpi_standalone", "satellite1_rpi_satellite"})
            for device in devices.values():
                self.assertEqual(set(device["artifacts"]), {"ota"})
                self.assertEqual(device["artifacts"]["ota"]["flash_transport"], "tater_native_ota")
                self.assertTrue(
                    device["artifacts"]["ota"]["path"].startswith(
                        "https://github.com/TaterTotterson/Tater-SAT1-RPi/releases/download/v1.2.3/"
                    )
                )
            latest = json.loads((release / "latest.json").read_text(encoding="utf-8"))
            self.assertEqual(set(latest["boards"]), set(devices))


if __name__ == "__main__":
    unittest.main()
