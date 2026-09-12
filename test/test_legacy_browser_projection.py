import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('legacy_projection', Path(__file__).resolve().parents[1] / 'provisioning/compat/legacy-browser-prepare.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class LegacyProjectionTests(unittest.TestCase):
    def test_only_display_fields_survive(self):
        self.assertEqual(module.project({'configured': True, 'password': 'private',
            'controllers': {'private': True}, 'views': [{'url': 'https://foundry.example', 'output': 'DP-1', 'secret': 'private'}]}),
            {'configured': True, 'views': [{'url': 'https://foundry.example', 'output': 'DP-1'}]})

    def test_first_boot(self):
        self.assertEqual(module.project({}), {'configured': False, 'views': []})

    def test_unsafe_values_rejected(self):
        for view in [{'url': 'file:///etc/passwd'}, {'url': 'https://user:secret@example.com'},
                     {'url': 'https://example.com\n--bad'}, {'output': 'DP-1"; exec bad'}]:
            with self.subTest(view=view), self.assertRaises(ValueError):
                module.project({'views': [view]})
