from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import subprocess
import tomllib
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
        self.assertIn(
            "tater_revision=v1.1.17:f5e955b00ee52cdfdce0aac4ea0099188c73fea0",
            completed.stdout,
        )
        self.assertIn("tater_update_policy=pinned_release", completed.stdout)
        self.assertIn("xmos_firmware=v1.1.1", completed.stdout)
        self.assertIn(
            "xmos_sha256=8ab57bd9da5f114746fcbc3d25ea57b32ea3938c61ed4b545d5d93a3d410c0e5",
            completed.stdout,
        )
        self.assertIn("first_boot_identity=unique_local_token", completed.stdout)
        self.assertIn("compression=xz", completed.stdout)
        self.assertIn("ota_format=tater_sat1_signed_bundle_v1", completed.stdout)
        self.assertIn("ssh_enabled=0", completed.stdout)
        self.assertIn("ssh_admin_user=tater", completed.stdout)

    def test_ssh_is_opt_in_and_requires_credentials(self) -> None:
        completed = subprocess.run(
            [str(ROOT / "scripts" / "build-pi-image.sh"), "--plan"],
            cwd=ROOT,
            env={"PATH": os.environ["PATH"], "PI_ENABLE_SSH": "1"},
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("requires an explicit PI_FIRST_USER_PASS or PI_FIRST_USER_PUBKEY", completed.stderr)

        builder = (ROOT / "scripts" / "build-pi-image.sh").read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/image.yml").read_text(encoding="utf-8")
        self.assertIn('PI_ENABLE_SSH="${PI_ENABLE_SSH:-0}"', builder)
        self.assertIn('PI_FIRST_USER_PASS="${PI_FIRST_USER_PASS:-tater}"', builder)
        self.assertIn('PI_FIRST_USER_NAME="${PI_FIRST_USER_NAME:-tater}"', builder)
        self.assertIn('PI_ENABLE_SSH: "0"', workflow)
        self.assertIn("PI_FIRST_USER_PASS: tater", workflow)
        self.assertIn('previous_tag=""', workflow)
        self.assertIn('if resolved_tag="$(gh api', workflow)
        self.assertIn('previous_tag="${resolved_tag}"', workflow)

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

        with (ROOT / "upstreams.toml").open("rb") as handle:
            xmos = tomllib.load(handle)["tater_native_xmos"]
        firmware = ROOT / "firmware/xmos/sat1_xmos_1_1_1_factory.bin"
        self.assertEqual(xmos["version"], "v1.1.1")
        self.assertEqual(hashlib.sha256(firmware.read_bytes()).hexdigest(), xmos["sha256"])

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
        self.assertIn("tater-sat1-leds.service", stage)
        self.assertIn("tater-sat1-audio-watchdog.timer", stage)
        self.assertIn('backend = "xmos"', stage)
        self.assertIn("test -x /opt/tater-sat1/venv/bin/tater-sat1-leds", stage)
        self.assertIn("test ! -e /opt/tater/app/tateros_app.py", stage)

    def test_image_normalizes_bundled_satellite_git_ownership(self) -> None:
        host_stage = (
            ROOT
            / "scripts"
            / "pi-image"
            / "stage-tater-sat1"
            / "00-install-appliance"
            / "00-run.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'chown -R 0:0 "${ROOTFS_DIR}/opt/tater-sat1/linux-satellite"',
            host_stage,
        )

    def test_image_includes_captive_portal_network_packages(self) -> None:
        packages = (ROOT / "scripts/pi-image/stage-tater-sat1/00-install-appliance/00-packages").read_text(
            encoding="utf-8"
        )
        self.assertIn("hostapd\n", packages)
        self.assertIn("dnsmasq-base\n", packages)
        self.assertIn("network-manager\n", packages)
        self.assertIn("openssl\n", packages)

    def test_image_enables_sat1_hardware_runtime_requirements(self) -> None:
        stage = (
            ROOT
            / "scripts"
            / "pi-image"
            / "stage-tater-sat1"
            / "00-install-appliance"
            / "01-run-chroot.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("dtoverlay=pwm,pin=12,func=4", stage)
        self.assertIn("startup_muted = true", stage)
        self.assertIn("startup_muted = false", stage)
        self.assertIn("tater-sat1-i2c.conf", stage)
        self.assertIn("90-tater-sat1-wifi-powersave.conf", stage)
        self.assertIn('audio_input_device = "satellite1_input"', stage)
        self.assertIn('audio_output_device = "pulse/satellite1_output"', stage)
        self.assertIn("import websockets", stage)
        self.assertIn("tater-sat1-audio-hardware", stage)
        self.assertIn("tater-sat1-xmos-firmware", stage)
        self.assertIn("sat1_xmos_1_1_1_factory.bin", stage)
        self.assertIn("tater-sat1-xmos.service", stage)
        packages = (
            ROOT / "scripts/pi-image/stage-tater-sat1/00-install-appliance/00-packages"
        ).read_text(encoding="utf-8")
        self.assertIn("flashrom\n", packages)
        self.assertIn("test -x /usr/sbin/flashrom", stage)
        self.assertNotIn("test -x /usr/bin/flashrom", stage)

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
        self.assertIn("prepare_tater_source.py", builder)
        self.assertIn(".tater-sat1-build.json", chroot_stage)
        self.assertNotIn("venv/bin/tater-sat1-app-update", chroot_stage)
        self.assertIn("tater-sat1-app-update.timer", chroot_stage)
        self.assertIn("test ! -L /etc/systemd/system/timers.target.wants/tater-sat1-app-update.timer", chroot_stage)

    def test_builder_writes_a_checksum_for_the_finished_image(self) -> None:
        builder = (ROOT / "scripts" / "build-pi-image.sh").read_text(encoding="utf-8")
        self.assertIn('SHA256SUMS.txt', builder)
        self.assertIn('pi-gen completed without producing an image', builder)
        self.assertIn('without producing a signed OTA bundle', builder)
        self.assertIn('tater_update_policy=${TATER_UPDATE_POLICY}', builder)
        self.assertIn('tater_revision=${TATER_REVISION:-not_bundled}', builder)


if __name__ == "__main__":
    unittest.main()
