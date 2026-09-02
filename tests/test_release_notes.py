from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build_release_notes", ROOT / "script/build_release_notes.py")
assert SPEC is not None and SPEC.loader is not None
release_notes = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release_notes
SPEC.loader.exec_module(release_notes)


class ReleaseNotesTests(unittest.TestCase):
    def test_default_release_repository_uses_the_rpi_name(self) -> None:
        self.assertEqual(release_notes.RELEASE_REPO, "TaterTotterson/Tater-SAT1-RPi")

    def test_workflow_compares_with_the_previous_published_release(self) -> None:
        workflow = (ROOT / ".github/workflows/image.yml").read_text(encoding="utf-8")
        self.assertIn('repos/${GITHUB_REPOSITORY}/releases/latest', workflow)
        self.assertIn('--previous-tag "${{ steps.previous_release.outputs.tag }}"', workflow)

    def test_first_release_lists_every_change_and_history(self) -> None:
        commits = [
            release_notes.Commit("a" * 40, "Add standalone image"),
            release_notes.Commit("b" * 40, "Add satellite image"),
        ]

        notes = release_notes.render_release_notes("owner/repo", "v0.1.0", None, commits)

        self.assertIn("## What's Changed", notes)
        self.assertIn("Add standalone image", notes)
        self.assertIn("[`aaaaaaa`](https://github.com/owner/repo/commit/", notes)
        self.assertIn("https://github.com/owner/repo/commits/v0.1.0", notes)

    def test_later_release_links_the_previous_version_comparison(self) -> None:
        notes = release_notes.render_release_notes("owner/repo", "v0.2.0", "v0.1.0", [])

        self.assertIn("No user-facing changes", notes)
        self.assertIn("https://github.com/owner/repo/compare/v0.1.0...v0.2.0", notes)

    def test_v014_highlights_stable_tater_app_updates(self) -> None:
        notes = release_notes.render_release_notes("owner/repo", "v0.1.4", "v0.1.3", [])

        self.assertIn("checks once daily", notes)
        self.assertIn("ordinary commits", notes)
        self.assertIn("automatically rolled back", notes)
        self.assertIn("Signed SAT1 firmware remains authoritative", notes)

    def test_v015_highlights_setup_handoff_and_satellite_identity(self) -> None:
        notes = release_notes.render_release_notes("owner/repo", "v0.1.5", "v0.1.4", [])

        self.assertIn("satellite name and room", notes)
        self.assertIn("without a full device reboot", notes)
        self.assertIn("frozen setup LEDs", notes)
        self.assertIn("voice service restarts automatically", notes)

    def test_v016_highlights_verified_four_microphone_xmos_support(self) -> None:
        notes = release_notes.render_release_notes("owner/repo", "v0.1.6", "v0.1.5", [])

        self.assertIn("XMOS `v1.1.1`", notes)
        self.assertIn("four-microphone beamforming", notes)
        self.assertIn("already-current device untouched", notes)
        self.assertIn("flash verification", notes)
        self.assertIn("signed appliance OTA", notes)

    def test_v017_highlights_pinned_tater_and_ota_only_updates(self) -> None:
        notes = release_notes.render_release_notes("owner/repo", "v0.1.7", "v0.1.6", [])

        self.assertIn("Tater `v1.1.16`", notes)
        self.assertIn("daily Tater downloader has been removed", notes)
        self.assertIn("signed SAT1 appliance OTA", notes)
        self.assertIn("full-appliance rollback", notes)

    def test_v018_highlights_memory_safe_tater_and_s420_handoff(self) -> None:
        notes = release_notes.render_release_notes("owner/repo", "v0.1.8", "v0.1.7", [])

        self.assertIn("Tater `v1.1.17`", notes)
        self.assertIn("streams large firmware downloads", notes)
        self.assertIn("Raspberry Pi Zero 2 W", notes)
        self.assertIn("ThirdReality S420 and SAT1 OTA", notes)
        self.assertIn("device-side health check", notes)
        self.assertIn("automatic rollback protection", notes)

    def test_v019_highlights_adaface_and_spudlink_model_sync(self) -> None:
        notes = release_notes.render_release_notes("owner/repo", "v0.1.9", "v0.1.8", [])

        self.assertIn("Tater `v1.1.22`", notes)
        self.assertIn("AdaFace IR-50 WebFace4M", notes)
        self.assertIn("retains FaceNet profiles for rollback", notes)
        self.assertIn("never compares embeddings from different models", notes)
        self.assertIn("without downloading AdaFace to the Spudlet", notes)

    def test_v0110_highlights_tater_update_and_persistent_core_storage(self) -> None:
        notes = release_notes.render_release_notes("owner/repo", "v0.1.10", "v0.1.9", [])

        self.assertIn("Tater `v1.1.23`", notes)
        self.assertIn("cores, Verbas, and portals", notes)
        self.assertIn("persistent, Tater-owned SAT1 storage", notes)
        self.assertIn("permission-denied errors", notes)
        self.assertIn("User-installed extensions now survive signed SAT1 appliance updates", notes)

    def test_v0111_highlights_airplay_image_build_repair(self) -> None:
        notes = release_notes.render_release_notes("owner/repo", "v0.1.11", "v0.1.10", [])

        self.assertIn("Tater `v1.1.23`", notes)
        self.assertIn("pinned native AirPlay receiver", notes)
        self.assertIn("PTP clock ports", notes)
        self.assertIn("Tater server remains unprivileged", notes)

    def test_v0112_highlights_first_boot_airplay_permissions(self) -> None:
        notes = release_notes.render_release_notes("owner/repo", "v0.1.12", "v0.1.11", [])

        self.assertIn("Raspberry Pi's first boot", notes)
        self.assertIn("restricted image-build container", notes)
        self.assertIn("Tater service unprivileged", notes)
        self.assertIn("checksum-verified AirPlay sender", notes)


if __name__ == "__main__":
    unittest.main()
