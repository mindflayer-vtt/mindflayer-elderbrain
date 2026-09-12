import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("validate_smtp", ROOT / "iso/validate-smtp.py")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class SmtpConfigTests(unittest.TestCase):
    def test_example_and_invalid_settings(self):
        example = json.loads((ROOT / "config/defaults/smtp.example.json").read_text())
        validator.validate(example)
        for field, value in (("port", True), ("port", 0), ("secure", "false"),
                             ("host", "bad\nhost"), ("password", None), ("from", "bad")):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validator.validate({**example, field: value})

    def test_private_config_is_explicit_and_installed_privately(self):
        builder = (ROOT / "iso/build.sh").read_text()
        self.assertIn('--exclude-from="$ROOT/iso/payload.exclude"', builder)
        self.assertIn('/config/private/', (ROOT / 'iso/payload.exclude').read_text())
        self.assertIn('install -m 0600 "$SMTP_CONFIG"', builder)
        self.assertIn('python3 "$ROOT/iso/validate-smtp.py" "$SMTP_CONFIG"', builder)
        installer = (ROOT / "provisioning/install.sh").read_text()
        self.assertIn('! -e "$STATE/elderbrain/secrets/default-smtp.json"', installer)
        self.assertIn('install -m 0600 -o 1000 -g 1000 "$PAYLOAD_DIR/config/private/smtp.json"', installer)
        self.assertIn("config/private/", (ROOT / ".gitignore").read_text())
