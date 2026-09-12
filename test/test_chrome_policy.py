import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ChromePolicyTests(unittest.TestCase):
    def test_password_saving_is_disabled_by_installed_mandatory_policy(self):
        policy = json.loads((ROOT / "provisioning/chrome/elderbrain.json").read_text())
        self.assertIs(policy["PasswordManagerEnabled"], False)
        installer = (ROOT / "provisioning/install.sh").read_text()
        self.assertIn('install -m 0644 "$PAYLOAD_DIR/provisioning/chrome/elderbrain.json" /etc/opt/chrome/policies/managed/elderbrain.json', installer)
