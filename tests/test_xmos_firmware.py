from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from tater_sat1_standalone.xmos_firmware import ensure_xmos_firmware, ensure_xmos_firmware_once, parse_version


class XmosFirmwareTests(unittest.TestCase):
    def _fixture(self, directory: str) -> tuple[Path, Path, str]:
        firmware = Path(directory) / "sat1_xmos_factory.bin"
        firmware.write_bytes(b"known XMOS factory image")
        tool = Path(directory) / "sat1-xmos"
        tool.write_text("#!/bin/sh\n", encoding="utf-8")
        digest = hashlib.sha256(firmware.read_bytes()).hexdigest()
        return firmware, tool, digest

    def test_parse_version_ignores_cli_noise(self) -> None:
        self.assertEqual(parse_version("setup complete\nv1.1.1\n"), "v1.1.1")
        self.assertEqual(parse_version("v1.0.4-alpha.8\n"), "v1.0.4-alpha.8")
        self.assertIsNone(parse_version("None\n"))

    def test_matching_firmware_is_left_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            firmware, tool, digest = self._fixture(directory)
            runner = mock.Mock(return_value=subprocess.CompletedProcess([], 0, "v1.1.1\n", ""))

            result = ensure_xmos_firmware(
                firmware,
                expected_sha256=digest,
                tool=tool,
                runner=runner,
                sleeper=mock.Mock(),
            )

        self.assertEqual(result.status, "unchanged")
        runner.assert_called_once_with(
            [str(tool), "read-firmware"],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_mismatched_firmware_is_written_verified_and_released_from_reset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            firmware, tool, digest = self._fixture(directory)
            versions = iter(("v1.0.3\n", "v1.1.1\n"))

            def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
                stdout = next(versions) if command[-1] == "read-firmware" else ""
                return subprocess.CompletedProcess(command, 1, stdout, "")

            runner = mock.Mock(side_effect=run)
            result = ensure_xmos_firmware(
                firmware,
                expected_sha256=digest,
                tool=tool,
                runner=runner,
                sleeper=mock.Mock(),
            )

        self.assertEqual(result.status, "updated")
        commands = [call.args[0] for call in runner.call_args_list]
        self.assertIn([str(tool), "-v", "flash-firmware", str(firmware), "--verify"], commands)
        self.assertIn([str(tool), "disable-flashing"], commands)

    def test_unverified_factory_image_is_never_written(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            firmware, tool, _digest = self._fixture(directory)
            runner = mock.Mock()

            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                ensure_xmos_firmware(
                    firmware,
                    expected_sha256="0" * 64,
                    tool=tool,
                    runner=runner,
                    sleeper=mock.Mock(),
                )

        runner.assert_not_called()

    def test_boot_marker_avoids_touching_spi_during_an_audio_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            firmware, tool, digest = self._fixture(directory)
            marker = Path(directory) / "run" / "verified.json"
            runner = mock.Mock(return_value=subprocess.CompletedProcess([], 0, "v1.1.1\n", ""))

            first = ensure_xmos_firmware_once(
                marker,
                firmware,
                expected_sha256=digest,
                tool=tool,
                runner=runner,
                sleeper=mock.Mock(),
            )
            second = ensure_xmos_firmware_once(
                marker,
                firmware,
                expected_sha256=digest,
                tool=tool,
                runner=runner,
                sleeper=mock.Mock(),
            )

        self.assertEqual(first.status, "unchanged")
        self.assertEqual(second.status, "already_verified_this_boot")
        self.assertEqual(runner.call_count, 1)


if __name__ == "__main__":
    unittest.main()
