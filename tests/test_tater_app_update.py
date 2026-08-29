from __future__ import annotations

import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock

from tater_sat1_standalone.tater_app_update import (
    AppLayout,
    Release,
    _extract_release,
    run_update,
    update_needed,
)


OLD_REVISION = "1" * 40
NEW_REVISION = "2" * 40
RELEASE = Release(
    tag="v1.2.3",
    published_at="2026-08-29T12:00:00Z",
    tarball_url="https://api.github.com/repos/TaterTotterson/Tater/tarball/v1.2.3",
    commit=NEW_REVISION,
)


def populate(layout: AppLayout, revision: str = OLD_REVISION) -> None:
    layout.config.parent.mkdir(parents=True, exist_ok=True)
    layout.config.write_text('[runtime]\nflavor = "standalone"\n', encoding="utf-8")
    app = layout.app_root / "app"
    app.mkdir(parents=True)
    (app / "tateros_app.py").write_text("app = object()\n", encoding="utf-8")
    (app / ".tater-sat1-build.json").write_text(
        json.dumps({"schema": 1, "tater_reference_revision": revision}) + "\n",
        encoding="utf-8",
    )
    (layout.app_root / "venv/bin").mkdir(parents=True)
    (layout.app_root / "venv/bin/python").write_text("#!/bin/sh\n", encoding="utf-8")


def release_slot(layout: AppLayout) -> Path:
    slot = layout.release_root / "v1.2.3-test"
    app = slot / "app"
    app.mkdir(parents=True)
    (app / "tateros_app.py").write_text("app = object()\n", encoding="utf-8")
    (app / ".tater-sat1-build.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "tater_reference_revision": NEW_REVISION,
                "tater_release_tag": RELEASE.tag,
                "tater_release_published_at": RELEASE.published_at,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (slot / "venv/bin").mkdir(parents=True)
    (slot / "venv/bin/python").write_text("#!/bin/sh\n", encoding="utf-8")
    return slot


class TaterAppUpdateTests(unittest.TestCase):
    def test_release_decision_never_downgrades_a_newer_bundled_commit(self) -> None:
        with mock.patch(
            "tater_sat1_standalone.tater_app_update._compare_status",
            return_value="ahead",
        ):
            needed, reason = update_needed(
                "TaterTotterson/Tater",
                RELEASE,
                {"tater_reference_revision": OLD_REVISION},
            )
        self.assertFalse(needed)
        self.assertEqual(reason, "bundled_tater_is_at_or_ahead_of_release")

    def test_release_decision_uses_only_a_newer_published_release(self) -> None:
        needed, reason = update_needed(
            "TaterTotterson/Tater",
            RELEASE,
            {
                "tater_reference_revision": OLD_REVISION,
                "tater_release_tag": "v1.2.4",
                "tater_release_published_at": "2026-08-30T12:00:00Z",
            },
        )
        self.assertFalse(needed)
        self.assertEqual(reason, "installed_release_is_newer")

    def test_check_only_reports_a_stable_release_without_switching(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            layout = AppLayout(Path(temporary))
            populate(layout)
            with (
                mock.patch("tater_sat1_standalone.tater_app_update.latest_release", return_value=RELEASE),
                mock.patch("tater_sat1_standalone.tater_app_update.update_needed", return_value=(True, "new")),
            ):
                result = run_update(layout, check_only=True)
            self.assertEqual(result["status"], "update_available")
            self.assertFalse(layout.app_root.is_symlink())

    def test_automatic_checks_can_be_disabled_without_contacting_github(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            layout = AppLayout(Path(temporary))
            populate(layout)
            with (
                mock.patch.dict(os.environ, {"TATER_APP_AUTO_UPDATE": "0"}, clear=False),
                mock.patch("tater_sat1_standalone.tater_app_update.latest_release") as release_lookup,
            ):
                result = run_update(layout, automatic=True)
            self.assertEqual(result["status"], "disabled")
            release_lookup.assert_not_called()

    def test_successful_release_switch_keeps_one_known_good_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            layout = AppLayout(Path(temporary))
            populate(layout)
            slot = release_slot(layout)
            environment = {
                "TATER_SAT1_UPDATE_NO_SYSTEMD": "1",
                "TATER_SAT1_APP_UPDATE_SKIP_HTTP_HEALTH": "1",
            }
            with (
                mock.patch.dict(os.environ, environment, clear=False),
                mock.patch("tater_sat1_standalone.tater_app_update.latest_release", return_value=RELEASE),
                mock.patch("tater_sat1_standalone.tater_app_update.update_needed", return_value=(True, "new")),
                mock.patch("tater_sat1_standalone.tater_app_update._setup_release", return_value=slot),
            ):
                result = run_update(layout)
            self.assertEqual(result["status"], "updated")
            self.assertTrue(layout.app_root.is_symlink())
            self.assertEqual(layout.app_root.resolve(), slot.resolve())
            slots = [path for path in layout.release_root.iterdir() if path.is_dir()]
            self.assertEqual(len(slots), 2)

    def test_failed_health_rolls_back_and_waits_for_the_next_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            layout = AppLayout(Path(temporary))
            populate(layout)
            slot = release_slot(layout)
            environment = {"TATER_SAT1_UPDATE_NO_SYSTEMD": "1"}
            patches = (
                mock.patch.dict(os.environ, environment, clear=False),
                mock.patch("tater_sat1_standalone.tater_app_update.latest_release", return_value=RELEASE),
                mock.patch("tater_sat1_standalone.tater_app_update.update_needed", return_value=(True, "new")),
                mock.patch("tater_sat1_standalone.tater_app_update._setup_release", return_value=slot),
                mock.patch("tater_sat1_standalone.tater_app_update._healthy", return_value=False),
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4]:
                failed = run_update(layout)
                waiting = run_update(layout)
            self.assertEqual(failed["status"], "rolled_back")
            self.assertEqual(failed["failed_release_tag"], RELEASE.tag)
            self.assertEqual(waiting["status"], "waiting_for_new_release")
            self.assertNotEqual(layout.app_root.resolve(), slot.resolve())

    def test_release_archive_rejects_links_and_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "release.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                payload = b"#!/bin/sh\n"
                setup = tarfile.TarInfo("Tater-test/setup_tater.sh")
                setup.size = len(payload)
                setup.mode = 0o755
                archive.addfile(setup, io.BytesIO(payload))
                link = tarfile.TarInfo("Tater-test/unsafe")
                link.type = tarfile.SYMTYPE
                link.linkname = "../../outside"
                archive.addfile(link)
            with self.assertRaisesRegex(ValueError, "unsupported entry"):
                _extract_release(archive_path, root / "output")


if __name__ == "__main__":
    unittest.main()
