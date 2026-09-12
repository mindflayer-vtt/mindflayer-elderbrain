import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('host_displays', ROOT / 'appliance/lib/host_displays.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class HostDisplaysTests(unittest.TestCase):
    def test_normalizes_active_and_inactive_outputs_without_exposing_other_state(self):
        result = module.normalize([
            {'name': 'DP-1', 'make': 'Vendor', 'model': 'Monitor', 'active': True,
             'current_mode': {'width': 1920, 'height': 1080, 'refresh': 60000}, 'scale': 1, 'serial': 'private'},
            {'name': 'HDMI-A-1', 'active': False, 'current_mode': None},
            {'name': 'bad"; exec arbitrary'},
        ])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['width'], 1920)
        self.assertNotIn('serial', result[0])
        self.assertFalse(result[1]['active'])
        self.assertIsNone(result[1]['width'])

    def test_missing_kiosk_socket_is_not_an_empty_success(self):
        with patch.object(module.pwd, 'getpwnam') as user, patch.object(Path, 'glob', return_value=[]):
            user.return_value.pw_uid = 999
            with self.assertRaisesRegex(ValueError, 'unavailable'):
                module.discover()

    def test_installation_wiring(self):
        self.assertIn('"$RUNTIME/host_displays.py"', (ROOT / 'provisioning/install.sh').read_text())
