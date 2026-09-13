from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FoundryVersionTests(unittest.TestCase):
    def test_default_core_meets_current_module_minimum(self):
        # Mindflayer 3.0.0 declares minimum core 14.367. Do not silently lower
        # its compatibility requirement to accommodate an older appliance pin.
        expected = ('ghcr.io/felddy/foundryvtt:14.367@sha256:'
                    '5004a67fbbef8e3f5f82afb01c8dbe06626c57519cad541a59b1bdce3c2a97ac')
        defaults = (ROOT / 'config/defaults/appliance.env').read_text().splitlines()
        self.assertIn('FOUNDRY_IMAGE=' + expected, defaults)
        self.assertIn('image: ${FOUNDRY_IMAGE:-' + expected + '}', (ROOT / 'compose/compose.yaml').read_text())
