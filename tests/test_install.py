from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    def test_dry_run_uses_latest_tater_and_pinned_satellite_profile(self) -> None:
        completed = subprocess.run(
            [str(ROOT / "script" / "install"), "--dry-run", "--skip-apt", "--no-enable"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = completed.stdout
        self.assertIn("git clone https://github.com/TaterTotterson/Tater.git /opt/tater/app", output)
        self.assertIn("checkout --detach f5e955b00ee52cdfdce0aac4ea0099188c73fea0", output)
        self.assertIn("4069417f495d9b5cf4dc9d0a38ce2fbb42d575ae", output)
        self.assertIn("TATER_SETUP_REQUIRE_LOCAL_LLM=0", output)
        self.assertIn("setup_tater.sh edge", output)
        self.assertIn("pip install --editable /opt/tater-sat1/linux-satellite", output)
        self.assertIn("tater-sat1-provisioning.service", output)
        self.assertIn("tater-sat1-leds.service", output)
        self.assertIn("config/pulse.pa", output)
        self.assertIn("config/pulse-client.conf", output)
        self.assertIn("set-source-volume satellite1_input 131072", (ROOT / "config" / "pulse.pa").read_text())
        self.assertIn("tater-sat1-i2c.conf", output)
        self.assertIn("90-tater-sat1-wifi-powersave.conf", output)
        self.assertIn("tater-sat1-wait-audio", output)
        self.assertIn("tater-sat1-audio-hardware", output)
        self.assertIn("sat1_xmos_1_1_1_factory.bin", output)
        self.assertIn("tater-sat1-xmos.service", output)
        self.assertIn("tater-sat1-xmos-firmware", (ROOT / "systemd/tater-sat1-audio.service").read_text())
        audio_hardware = (ROOT / "script" / "audio-hardware").read_text()
        self.assertIn('0x1a 0x00', audio_hardware)
        self.assertIn('0x02 0x80', audio_hardware)
        self.assertIn("tater-sat1-audio-watchdog", output)
        self.assertIn("websockets>=12,<16", output)
        self.assertIn("tater-sat1-setup-hotspot", output)
        setup_hotspot = (ROOT / "script" / "setup-hotspot").read_text()
        self.assertIn('ACTIVE_FILE="${RUNTIME_DIR}/active"', setup_hotspot)
        self.assertIn(': > "${ACTIVE_FILE}"', setup_hotspot)
        self.assertIn("tater-sat1-apply-update", output)
        self.assertIn("tater-sat1-update.path", output)
        # Inert units are retained only for OTA compatibility with older cards.
        self.assertIn("tater-sat1-app-update.service", output)
        self.assertIn("tater-sat1-app-update.timer", output)
        self.assertNotIn("tater-app-update.env.example", output)
        self.assertNotIn("tater-sat1-app-update --automatic", output)
        self.assertIn("update-public.pem", output)
        self.assertNotIn("apt-get update", output)

    def test_satellite_dry_run_omits_local_tater(self) -> None:
        completed = subprocess.run(
            [
                str(ROOT / "script" / "install"),
                "--flavor",
                "satellite",
                "--dry-run",
                "--skip-apt",
                "--no-enable",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = completed.stdout
        self.assertIn("config.satellite.toml.example", output)
        self.assertIn("tater-sat1-satellite.service", output)
        self.assertIn("pip install --editable /opt/tater-sat1/linux-satellite", output)
        self.assertIn("tater-sat1-provisioning.service", output)
        self.assertIn("config/pulse.pa", output)
        self.assertIn("config/pulse-client.conf", output)
        self.assertIn("set-source-volume satellite1_input 131072", (ROOT / "config" / "pulse.pa").read_text())
        self.assertIn("tater-sat1-i2c.conf", output)
        self.assertIn("90-tater-sat1-wifi-powersave.conf", output)
        self.assertIn("tater-sat1-wait-audio", output)
        self.assertIn("tater-sat1-audio-hardware", output)
        self.assertIn("sat1_xmos_1_1_1_factory.bin", output)
        self.assertIn("tater-sat1-xmos.service", output)
        self.assertIn("tater-sat1-audio-watchdog", output)
        self.assertNotIn("websockets>=12,<16", output)
        self.assertNotIn("setup_tater.sh edge", output)
        self.assertNotIn("tater-sat1-app-update.service", output)
        self.assertNotIn("tater-sat1-app-update.timer", output)
        self.assertNotIn("git clone https://github.com/TaterTotterson/Tater.git", output)


if __name__ == "__main__":
    unittest.main()
