import contextlib
import io
from pathlib import Path
import tempfile
import unittest

from tater_sat1_standalone.cli import main


class CliTests(unittest.TestCase):
    def test_plan_redacts_shared_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.toml"
            config_path.write_text(
                f'[runtime]\nstate_dir = "{root / "state"}"\n',
                encoding="utf-8",
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                main(["--config", str(config_path), "plan", "tater"])
            rendered = output.getvalue()
            self.assertIn("TATER_NATIVE_SATELLITE_TOKEN=<redacted>", rendered)
            self.assertFalse((root / "state").exists())


if __name__ == "__main__":
    unittest.main()
