from pathlib import Path
import tempfile
import unittest

from tater_sat1_standalone.config import StandaloneConfig, load_config


class ConfigTests(unittest.TestCase):
    def test_defaults_are_remote_appliance_defaults(self) -> None:
        config = StandaloneConfig.from_mapping({})
        self.assertEqual(config.runtime.flavor, "standalone")
        self.assertEqual(config.tater.port, 8501)
        self.assertEqual(config.satellite.board, "satellite1_rpi_standalone")
        self.assertEqual(config.runtime.satellite_executable.name, "tater-sat1-voice")
        self.assertEqual(config.satellite.pulse_server, "unix:/run/tater-sat1-audio/pulse/native")
        self.assertEqual(config.runtime.token_path.name, "native-satellite-token")
        self.assertEqual(config.runtime.satellite_name_path.name, "satellite-name")
        self.assertEqual(config.runtime.satellite_room_path.name, "satellite-room")
        self.assertTrue(config.leds.enabled)
        self.assertEqual(config.leds.backend, "xmos")
        self.assertEqual(config.leds.pixel_count, 24)
        self.assertEqual(config.leds.spi_bus, 0)
        self.assertEqual(config.leds.spi_device, 0)
        self.assertEqual(config.leds.gpio_pin, 12)
        self.assertEqual(config.leds.playback_monitor, "satellite1_output.monitor")

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
[leds]
brightness = 0.5
gpio_pin = 18
""".strip(),
                encoding="utf-8",
            )
            config = load_config(path)
        self.assertEqual(config.runtime.state_dir, Path("/tmp/tater-state"))
        self.assertEqual(config.tater.port, 9501)
        self.assertEqual(config.tater.extra_args, ("--log-level", "debug"))
        self.assertEqual(config.satellite.room, "Kitchen")
        self.assertEqual(config.leds.brightness, 0.5)
        self.assertEqual(config.leds.gpio_pin, 18)

    def test_rejects_invalid_extra_arguments(self) -> None:
        with self.assertRaisesRegex(ValueError, "array of strings"):
            StandaloneConfig.from_mapping({"satellite": {"extra_args": "--debug"}})

    def test_rejects_invalid_flavor(self) -> None:
        with self.assertRaisesRegex(ValueError, "runtime flavor"):
            StandaloneConfig.from_mapping({"runtime": {"flavor": "server"}})

    def test_satellite_flavor_gets_its_ota_board_identity(self) -> None:
        config = StandaloneConfig.from_mapping({"runtime": {"flavor": "satellite"}})
        self.assertEqual(config.satellite.board, "satellite1_rpi_satellite")

    def test_rejects_odd_led_ring_or_invalid_brightness(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be even"):
            StandaloneConfig.from_mapping({"leds": {"pixel_count": 23}})
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            StandaloneConfig.from_mapping({"leds": {"brightness": 1.1}})

    def test_xmos_led_backend_requires_the_production_24_pixel_ring(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be 24"):
            StandaloneConfig.from_mapping({"leds": {"backend": "xmos", "pixel_count": 12}})
        config = StandaloneConfig.from_mapping({"leds": {"backend": "gpio", "pixel_count": 12}})
        self.assertEqual(config.leds.pixel_count, 12)


if __name__ == "__main__":
    unittest.main()
