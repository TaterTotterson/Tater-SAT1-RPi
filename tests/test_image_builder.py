from __future__ import annotations

from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ImageBuilderTests(unittest.TestCase):
    def test_plan_uses_immutable_bookworm_inputs(self) -> None:
        completed = subprocess.run(
            [str(ROOT / "scripts" / "build-pi-image.sh"), "--plan"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("base_release=bookworm", completed.stdout)
        self.assertIn("pi_gen_revision=67262a4ad0959aab2a9d84a6392b1967999e8f50", completed.stdout)
        self.assertIn("sat1_release=v0.1.4", completed.stdout)
        self.assertIn("image_flavor=standalone", completed.stdout)
        self.assertIn("first_boot_identity=unique_local_token", completed.stdout)
        self.assertIn("compression=xz", completed.stdout)
        self.assertIn("ota_format=tater_sat1_signed_bundle_v1", completed.stdout)

    def test_satellite_plan_omits_tater_and_uses_device_pairing(self) -> None:
        completed = subprocess.run(
            [str(ROOT / "scripts" / "build-pi-image.sh"), "--flavor", "satellite", "--plan"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("image_name=tater-sat1-satellite", completed.stdout)
        self.assertIn("image_flavor=satellite", completed.stdout)
        self.assertIn("tater_revision=not_bundled", completed.stdout)
        self.assertIn("first_boot_identity=unique_device_pairing", completed.stdout)

    def test_hardware_assets_have_sha256_pins(self) -> None:
        lock_text = (ROOT / "packaging" / "image.lock").read_text(encoding="utf-8")
        checksums = re.findall(r"^SAT1_[A-Z]+_SHA256=([0-9a-f]{64})$", lock_text, re.MULTILINE)
        self.assertEqual(len(checksums), 3)
        self.assertIn("SAT1_RELEASE_TAG=v0.1.4", lock_text)

    def test_image_defers_device_identity_until_first_boot(self) -> None:
        stage = (
            ROOT
            / "scripts"
            / "pi-image"
            / "stage-tater-sat1"
            / "00-install-appliance"
            / "01-run-chroot.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("--defer-init", stage)
        self.assertIn("test ! -e /var/lib/tater-sat1-standalone/native-satellite-token", stage)
        self.assertIn("tater-sat1-firstboot.service", stage)
        self.assertIn("tater-sat1-provisioning.service", stage)
        self.assertIn("test ! -e /opt/tater/app/tateros_app.py", stage)

    def test_image_includes_captive_portal_network_packages(self) -> None:
        packages = (ROOT / "scripts/pi-image/stage-tater-sat1/00-install-appliance/00-packages").read_text(
            encoding="utf-8"
        )
        self.assertIn("hostapd\n", packages)
        self.assertIn("dnsmasq-base\n", packages)
        self.assertIn("network-manager\n", packages)
        self.assertIn("openssl\n", packages)

    def test_image_builds_and_enables_a_signed_ota_bundle(self) -> None:
        stage_root = ROOT / "scripts/pi-image/stage-tater-sat1/00-install-appliance"
        chroot_stage = (stage_root / "01-run-chroot.sh").read_text(encoding="utf-8")
        bundle_stage = (stage_root / "02-run.sh").read_text(encoding="utf-8")
        builder = (ROOT / "scripts/build-pi-image.sh").read_text(encoding="utf-8")
        self.assertIn("tater-sat1-update.path", chroot_stage)
        self.assertIn("tater-sat1-update-health.service", chroot_stage)
        self.assertIn("build_ota_bundle.py", bundle_stage)
        self.assertIn("on_chroot <<EOF", bundle_stage)
        self.assertIn("trap cleanup EXIT", bundle_stage)
        self.assertIn("TATER_SAT1_OTA_PRIVATE_KEY_PEM", builder)
        self.assertIn("keys/update-public.pem", builder)

    def test_builder_writes_a_checksum_for_the_finished_image(self) -> None:
        builder = (ROOT / "scripts" / "build-pi-image.sh").read_text(encoding="utf-8")
        self.assertIn('SHA256SUMS.txt', builder)
        self.assertIn('pi-gen completed without producing an image', builder)
        self.assertIn('without producing a signed OTA bundle', builder)


if __name__ == "__main__":
    unittest.main()
