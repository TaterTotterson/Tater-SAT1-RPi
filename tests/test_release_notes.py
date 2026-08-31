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


if __name__ == "__main__":
    unittest.main()
