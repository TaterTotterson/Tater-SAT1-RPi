from pathlib import Path
import tempfile
import unittest

from tater_sat1_standalone.config import StandaloneConfig, load_config


class ConfigTests(unittest.TestCase):
    def test_defaults_are_remote_appliance_defaults(self) -> None:
        config = StandaloneConfig.from_mapping({})
        self.assertEqual(config.tater.port, 8501)
        self.assertEqual(config.satellite.board, "satellite1_rpi")
        self.assertEqual(config.runtime.token_path.name, "native-satellite-token")

    def test_loads_paths_and_extra_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.toml"
            path.write_text(
                """
[runtime]
state_dir = "/tmp/tater-state"
[tater]
port = 9501
extra_args = ["--log-level", "debug"]
[satellite]
room = "Kitchen"
extra_args = ["--debug"]
""".strip(),
                encoding="utf-8",
            )
            config = load_config(path)
        self.assertEqual(config.runtime.state_dir, Path("/tmp/tater-state"))
        self.assertEqual(config.tater.port, 9501)
        self.assertEqual(config.tater.extra_args, ("--log-level", "debug"))
        self.assertEqual(config.satellite.room, "Kitchen")

    def test_rejects_invalid_extra_arguments(self) -> None:
        with self.assertRaisesRegex(ValueError, "array of strings"):
            StandaloneConfig.from_mapping({"satellite": {"extra_args": "--debug"}})


if __name__ == "__main__":
    unittest.main()

