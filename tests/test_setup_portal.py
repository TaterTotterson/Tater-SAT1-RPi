import tempfile
import unittest
from unittest import mock

from tater_sat1_standalone.config import StandaloneConfig
from tater_sat1_standalone.setup_portal import (
    NETWORK_CONNECTION_NAME,
    build_page,
    networkmanager_commands,
    save_configuration,
    validate_fields,
)


class SetupPortalValidationTests(unittest.TestCase):
    def standalone_config(self) -> StandaloneConfig:
        return StandaloneConfig.from_mapping({"runtime": {"flavor": "standalone"}})

    def satellite_config(self, state_dir: str) -> StandaloneConfig:
        return StandaloneConfig.from_mapping(
            {"runtime": {"flavor": "satellite", "state_dir": state_dir}}
        )

    def test_standalone_requires_only_wifi(self) -> None:
        values = validate_fields(
            self.standalone_config(),
            {"ssid": "Tater Lab", "wifi_password": "potato-pass"},
        )
        self.assertEqual(values["ssid"], "Tater Lab")
        self.assertEqual(values["tater_server"], "")
        self.assertEqual(values["pairing_code"], "")

    def test_satellite_requires_server_and_pairing_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self.satellite_config(temp_dir)
            values = validate_fields(
                config,
                {
                    "ssid": "Tater Lab",
                    "wifi_password": "potato-pass",
                    "tater_server": "http://main-tater.local:8501/",
                    "pairing_code": "123456",
                },
            )
            self.assertEqual(values["tater_server"], "http://main-tater.local:8501")
            for fields in (
                {"ssid": "Tater Lab", "wifi_password": "potato-pass"},
                {
                    "ssid": "Tater Lab",
                    "wifi_password": "potato-pass",
                    "tater_server": "ftp://bad.example",
                    "pairing_code": "123456",
                },
            ):
                with self.subTest(fields=fields), self.assertRaises(ValueError):
                    validate_fields(config, fields)

    def test_rejects_invalid_wifi_values(self) -> None:
        config = self.standalone_config()
        for fields in (
            {"ssid": "", "wifi_password": "potato-pass"},
            {"ssid": "x" * 33, "wifi_password": "potato-pass"},
            {"ssid": "Lab", "wifi_password": "short"},
            {"ssid": "bad\nnetwork", "wifi_password": "potato-pass"},
        ):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                validate_fields(config, fields)

    def test_page_changes_fields_by_flavor(self) -> None:
        standalone_page = build_page(self.standalone_config())
        self.assertIn('name="ssid"', standalone_page)
        self.assertNotIn('name="pairing_code"', standalone_page)
        with tempfile.TemporaryDirectory() as temp_dir:
            satellite_page = build_page(self.satellite_config(temp_dir))
        self.assertIn('name="ssid"', satellite_page)
        self.assertIn('name="tater_server"', satellite_page)
        self.assertIn('name="pairing_code"', satellite_page)
        self.assertNotIn("https://", satellite_page)


class SetupPortalPersistenceTests(unittest.TestCase):
    def test_networkmanager_commands_do_not_use_a_shell(self) -> None:
        commands = networkmanager_commands('Lab "WiFi"', r"eight\chars")
        self.assertEqual(commands[0], ("nmcli", "connection", "delete", NETWORK_CONNECTION_NAME))
        self.assertIn('Lab "WiFi"', commands[1])
        self.assertIn(r"eight\chars", commands[-1])
        self.assertNotIn("sh", commands[0])

    def test_save_writes_wifi_profile_and_private_pairing_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = StandaloneConfig.from_mapping(
                {"runtime": {"flavor": "satellite", "state_dir": temp_dir}}
            )
            completed = mock.Mock()
            runner = mock.Mock(return_value=completed)
            with mock.patch("tater_sat1_standalone.setup_portal.os.sync"):
                save_configuration(
                    config,
                    {
                        "ssid": "My Network",
                        "wifi_password": "potato-pass",
                        "tater_server": "https://tater.example.test",
                        "pairing_code": "pair-me",
                    },
                    runner=runner,
                )

            commands = [call.args[0] for call in runner.call_args_list]
            self.assertIn("My Network", commands[1])
            self.assertIn("potato-pass", commands[-1])
            self.assertEqual(config.runtime.token_path.read_text(encoding="utf-8").strip(), "pair-me")
            self.assertEqual(config.runtime.server_url_path.read_text(encoding="utf-8").strip(), "https://tater.example.test")
            self.assertEqual(config.runtime.token_path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
