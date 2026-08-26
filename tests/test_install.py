from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    def test_dry_run_uses_pinned_remote_only_profile(self) -> None:
        completed = subprocess.run(
            [str(ROOT / "script" / "install"), "--dry-run", "--skip-apt", "--no-enable"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = completed.stdout
        self.assertIn("67bd00361622b01bc167233b13d0feaeef0a4fc0", output)
        self.assertIn("5fcba46b1f5262efc3c49c4e43ef093222f42843", output)
        self.assertIn("TATER_SETUP_REQUIRE_LOCAL_LLM=0", output)
        self.assertIn("setup_tater.sh edge", output)
        self.assertIn("pip install --editable /opt/tater-sat1/linux-satellite", output)
        self.assertIn("tater-sat1-provisioning.service", output)
        self.assertIn("tater-sat1-setup-hotspot", output)
        self.assertIn("tater-sat1-apply-update", output)
        self.assertIn("tater-sat1-update.path", output)
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
        self.assertNotIn("setup_tater.sh edge", output)
        self.assertNotIn("git clone https://github.com/TaterTotterson/Tater.git", output)


if __name__ == "__main__":
    unittest.main()
