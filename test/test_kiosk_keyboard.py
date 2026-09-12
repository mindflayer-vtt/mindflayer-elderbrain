import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import os
import socket

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("kiosk_keyboard", ROOT / "appliance/lib/kiosk_keyboard.py")
keyboard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(keyboard)


class KioskKeyboardTests(unittest.TestCase):
    def test_catalog_includes_variants_and_excludes_command_syntax(self):
        with tempfile.TemporaryDirectory() as directory:
            rules = Path(directory) / "rules.xml"
            rules.write_text('<xkbConfigRegistry><layoutList><layout><configItem><name>de</name><description>German</description></configItem><variantList><variant><configItem><name>nodeadkeys</name><description>German (no dead keys)</description></configItem></variant></variantList></layout><layout><configItem><name>us;exec</name></configItem></layout></layoutList></xkbConfigRegistry>')
            self.assertEqual(keyboard.layouts(rules), [
                {"value": "de:", "label": "German"},
                {"value": "de:nodeadkeys", "label": "German (no dead keys)"}])

    def test_private_capability_and_allowlisted_command(self):
        token = "a" * 64
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            credential = runtime / "keyboard-token"
            credential.write_text(token)
            credential.chmod(0o600)
            with socket.socket(socket.AF_UNIX) as listener:
                listener.bind(str(runtime / "sway-ipc.test.sock"))
                with patch.object(keyboard, "RUNTIME", runtime), patch.object(keyboard.pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=os.getuid())), patch.object(keyboard, "layouts", return_value=[{"value": "de:", "label": "German"}]), patch.object(keyboard.subprocess, "run") as run:
                    for invalid in ("", "b" * 64, "x\nstatus"):
                        with self.assertRaises(ValueError): keyboard.operate(invalid)
                    with self.assertRaises(ValueError): keyboard.operate(token, "de:;exec")
                    run.assert_not_called()
                    run.side_effect = [SimpleNamespace(stdout='[{"success":true}]'), SimpleNamespace(stdout='[{"type":"keyboard","xkb_active_layout_name":"German"}]')]
                    self.assertEqual(keyboard.operate(token, "de:")["active"], ["German"])
                    self.assertIn('xkb_layout de', run.call_args_list[0].args[0][-1])
                    self.assertNotIn("shell", run.call_args_list[0].kwargs)
                    credential.chmod(0o644)
                    with self.assertRaises(ValueError): keyboard.operate(token)

    def test_missing_capability_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(keyboard, "RUNTIME", Path(directory)), patch.object(keyboard.pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=os.getuid())):
            with self.assertRaises(FileNotFoundError): keyboard.operate("a" * 64)
