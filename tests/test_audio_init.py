from dataclasses import dataclass
from pathlib import Path
import runpy
import sys
from types import ModuleType
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


@dataclass
class PDContract:
    voltage: float | None
    current: float | None


class AudioInitTests(unittest.TestCase):
    def initialize(self, contract):
        audio_out = ModuleType("satellite1.audio_out")
        audio_out.get_pd_contract = lambda: contract
        package = ModuleType("satellite1")
        package.audio_out = audio_out
        cli = ModuleType("satellite1.cli.cli_sat1")
        observed = []

        def vendor_main(argv):
            self.assertEqual(argv, ["dac", "setup"])
            current = audio_out.get_pd_contract()
            # Reproduce the SDK's unguarded access that failed on the Pi.
            mode = 2 if current.voltage and current.voltage >= 9 else 0
            observed.append((current, mode))
            return 0

        cli.main = vendor_main
        power = ModuleType("satellite1.components.power_delivery")
        power.PDContract = PDContract
        with patch.dict(sys.modules, {
            "satellite1": package,
            "satellite1.cli.cli_sat1": cli,
            "satellite1.components.power_delivery": power,
        }):
            namespace = runpy.run_path(str(ROOT / "script/init-audio"))
            self.assertEqual(namespace["main"](), 0)
        return observed[0]

    def test_plain_usb_initializes_in_low_voltage_mode(self):
        contract, mode = self.initialize(None)
        self.assertIsNone(contract.voltage)
        self.assertEqual(mode, 0)

    def test_pd_supply_keeps_its_negotiated_mode(self):
        expected = PDContract(voltage=9, current=2)
        contract, mode = self.initialize(expected)
        self.assertIs(contract, expected)
        self.assertEqual(mode, 2)
