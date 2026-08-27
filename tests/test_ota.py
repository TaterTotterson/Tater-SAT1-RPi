from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "script"))

from build_ota_bundle import build_bundle  # noqa: E402
from tater_sat1_standalone.ota import validate_update_integrity, validate_update_url  # noqa: E402
from tater_sat1_standalone.update_health import run_health_check  # noqa: E402
from tater_sat1_standalone.update_installer import (  # noqa: E402
    Layout,
    apply_pending,
    managed_directories,
    managed_files,
    verify_bundle,
)


def populate_rootfs(root: Path, flavor: str, version: str, marker: str) -> None:
    for relative in managed_directories(flavor):
        (root / relative).mkdir(parents=True, exist_ok=True)
    for relative in managed_files(flavor):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{marker}:{relative}\n", encoding="utf-8")
    (root / "etc/tater-sat1-standalone/version").write_text(version + "\n", encoding="utf-8")
    launcher = root / "opt/tater-sat1/venv/bin/tater-sat1-voice"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    launcher.chmod(0o755)
    (root / "opt/tater-sat1/release-marker").write_text(marker + "\n", encoding="utf-8")
    if flavor == "standalone":
        app = root / "opt/tater/app/tateros_app.py"
        app.parent.mkdir(parents=True, exist_ok=True)
        app.write_text(marker + "\n", encoding="utf-8")


class OtaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.key_dir = tempfile.TemporaryDirectory()
        cls.private_key = Path(cls.key_dir.name) / "private.pem"
        cls.public_key = Path(cls.key_dir.name) / "public.pem"
        subprocess.run(
            [
                "openssl",
                "genpkey",
                "-algorithm",
                "RSA",
                "-pkeyopt",
                "rsa_keygen_bits:2048",
                "-out",
                str(cls.private_key),
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["openssl", "pkey", "-in", str(cls.private_key), "-pubout", "-out", str(cls.public_key)],
            check=True,
            capture_output=True,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.key_dir.cleanup()

    def _bundle(self, directory: Path, flavor: str, version: str = "tater-sat1-test-v2") -> Path:
        candidate = directory / "candidate"
        populate_rootfs(candidate, flavor, version, "new")
        bundle = directory / f"{flavor}.sat1"
        build_bundle(candidate, flavor, version, self.private_key, bundle)
        return bundle

    def test_download_metadata_validation_rejects_unsafe_values(self) -> None:
        self.assertEqual(validate_update_url("https://example.test/update.sat1"), "https://example.test/update.sat1")
        with self.assertRaises(ValueError):
            validate_update_url("file:///tmp/update.sat1")
        with self.assertRaises(ValueError):
            validate_update_integrity("not-a-sha", 10)
        with self.assertRaises(ValueError):
            validate_update_integrity("0" * 64, 0)

    def test_led_controller_is_part_of_both_signed_ota_flavors(self) -> None:
        led_unit = "etc/systemd/system/tater-sat1-leds.service"
        self.assertIn(led_unit, managed_files("standalone"))
        self.assertIn(led_unit, managed_files("satellite"))

    def test_signed_bundle_verifies_for_only_its_flavor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = self._bundle(root, "standalone")
            work = root / "verify"
            manifest, payload = verify_bundle(bundle, self.public_key, "standalone", work)
            self.assertEqual(manifest["version"], "tater-sat1-test-v2")
            self.assertTrue((payload / "opt/tater/app/tateros_app.py").is_file())

            with self.assertRaisesRegex(ValueError, "does not match installed"):
                verify_bundle(bundle, self.public_key, "satellite", root / "wrong-flavor")

    def test_changed_signed_manifest_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = self._bundle(root, "satellite")
            extracted = root / "container"
            extracted.mkdir()
            with tarfile.open(bundle, "r") as archive:
                archive.extractall(extracted)
            manifest = json.loads((extracted / "manifest.json").read_text(encoding="utf-8"))
            manifest["version"] = "tater-sat1-tampered"
            (extracted / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            changed = root / "changed.sat1"
            with tarfile.open(changed, "w") as archive:
                for name in ("manifest.json", "manifest.sig", "payload.tar.xz"):
                    archive.add(extracted / name, arcname=name)
            with self.assertRaisesRegex(ValueError, "signature verification failed"):
                verify_bundle(changed, self.public_key, "satellite", root / "changed-verify")

    def _installed_layout(self, root: Path, flavor: str) -> Layout:
        populate_rootfs(root, flavor, "tater-sat1-test-v1", "old")
        config = root / "etc/tater-sat1-standalone/config.toml"
        config.write_text(f'[runtime]\nflavor = "{flavor}"\n', encoding="utf-8")
        shutil.copy2(self.public_key, root / "etc/tater-sat1-standalone/update-public.pem")
        state = root / "var/lib/tater-sat1-standalone"
        state.mkdir(parents=True, exist_ok=True)
        (state / "native-satellite-token").write_text("keep-me\n", encoding="utf-8")
        return Layout(root)

    def test_apply_and_health_accept_preserve_configuration_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "installed"
            layout = self._installed_layout(root, "standalone")
            original_config = layout.config.read_text(encoding="utf-8")
            bundle = self._bundle(Path(temporary) / "release", "standalone")
            layout.update_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bundle, layout.pending_bundle)
            environment = {
                "TATER_SAT1_UPDATE_NO_SYSTEMD": "1",
                "TATER_SAT1_UPDATE_NO_REBOOT": "1",
                "TATER_SAT1_UPDATE_HEALTH_WAIT_SECONDS": "0",
                "TATER_SAT1_UPDATE_HEALTH_ATTEMPTS": "1",
                "TATER_SAT1_UPDATE_SKIP_HTTP_HEALTH": "1",
            }
            with mock.patch.dict(os.environ, environment, clear=False):
                result = apply_pending(layout)
                health = run_health_check(layout)
            self.assertTrue(result["ok"])
            self.assertEqual(health["status"], "accepted")
            self.assertEqual(layout.version.read_text(encoding="utf-8").strip(), "tater-sat1-test-v2")
            self.assertEqual(layout.config.read_text(encoding="utf-8"), original_config)
            self.assertEqual((layout.state_dir / "native-satellite-token").read_text(encoding="utf-8"), "keep-me\n")
            self.assertEqual((root / "opt/tater-sat1/release-marker").read_text(encoding="utf-8"), "new\n")
            self.assertFalse(layout.rollback_dir.exists())

    def test_failed_health_check_restores_previous_appliance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "installed"
            layout = self._installed_layout(root, "satellite")
            bundle = self._bundle(Path(temporary) / "release", "satellite")
            layout.update_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bundle, layout.pending_bundle)
            environment = {
                "TATER_SAT1_UPDATE_NO_SYSTEMD": "1",
                "TATER_SAT1_UPDATE_NO_REBOOT": "1",
                "TATER_SAT1_UPDATE_HEALTH_WAIT_SECONDS": "0",
                "TATER_SAT1_UPDATE_HEALTH_ATTEMPTS": "1",
            }
            with mock.patch.dict(os.environ, environment, clear=False):
                apply_pending(layout)
                layout.version.write_text("broken\n", encoding="utf-8")
                health = run_health_check(layout)
            self.assertEqual(health["status"], "rolled_back")
            self.assertEqual(layout.version.read_text(encoding="utf-8").strip(), "tater-sat1-test-v1")
            self.assertEqual((root / "opt/tater-sat1/release-marker").read_text(encoding="utf-8"), "old\n")
            self.assertEqual((layout.state_dir / "native-satellite-token").read_text(encoding="utf-8"), "keep-me\n")


if __name__ == "__main__":
    unittest.main()
