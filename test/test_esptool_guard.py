import importlib.util
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


class EsptoolGuardTests(unittest.TestCase):
    def test_mac_guard_runs_before_each_operation_on_its_connected_chip(self):
        originals = {name: Mock() for name in ("chip_id", "flash_id", "read_flash", "write_flash")}
        esptool = SimpleNamespace(**originals, FatalError=RuntimeError)
        spec = importlib.util.spec_from_file_location("guarded_esptool", Path(__file__).resolve().parents[1] / "appliance/lib/esptool-runner.py")
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"esptool": esptool}):
            spec.loader.exec_module(module)
        module.require_mac("12:34:56:78:90:ab")
        for name, original in originals.items():
            wrong = SimpleNamespace(read_mac=lambda: (1, 2, 3, 4, 5, 6))
            with self.assertRaisesRegex(RuntimeError, "MAC changed"):
                getattr(esptool, name)(wrong, "arguments")
            original.assert_not_called()
            right = SimpleNamespace(read_mac=lambda: (0x12, 0x34, 0x56, 0x78, 0x90, 0xab))
            getattr(esptool, name)(right, "arguments")
            original.assert_called_once_with(right, "arguments")
        with self.assertRaises(ValueError):
            module.require_mac("invalid")


if __name__ == "__main__":
    unittest.main()
