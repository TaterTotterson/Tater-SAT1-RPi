from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "script" / "prepare_tater_source.py"
SPEC = importlib.util.spec_from_file_location("prepare_tater_source", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load prepare_tater_source.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TaterSourceTests(unittest.TestCase):
    def source(self, root: Path, block: str) -> Path:
        source = root / "source"
        pipeline = source / "tater_voice" / "voice_pipeline" / "__init__.py"
        pipeline.parent.mkdir(parents=True)
        pipeline.write_text("import os\nfrom typing import Any, Optional\n\n" + block, encoding="utf-8")
        (source / "setup_tater.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (source / ".git").mkdir()
        return source

    def test_adds_sat1_environment_fallback_and_records_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.source(root, MODULE.OLD_SETTINGS_BLOCK)
            destination = root / "prepared"

            metadata = MODULE.prepare(source, destination, "a" * 40, release_tag="v1.1.16")

            pipeline = (destination / MODULE.VOICE_PIPELINE).read_text(encoding="utf-8")
            self.assertIn("def _voice_setting_or_environment", pipeline)
            self.assertNotIn("_voice_settings().get(name)", pipeline)
            self.assertFalse((destination / ".git").exists())
            self.assertEqual(metadata["overlays"], ["sat1_voice_environment_defaults"])
            recorded = json.loads((destination / ".tater-sat1-build.json").read_text(encoding="utf-8"))
            self.assertEqual(recorded["tater_reference_revision"], "a" * 40)
            self.assertEqual(recorded["tater_release_tag"], "v1.1.16")

    def test_accepts_tater_after_upstream_absorbs_the_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.source(root, MODULE.SAT1_SETTINGS_BLOCK)

            metadata = MODULE.prepare(source, root / "prepared", "b" * 40)

            self.assertEqual(metadata["overlays"], [])


if __name__ == "__main__":
    unittest.main()
