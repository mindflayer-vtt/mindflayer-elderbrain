import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("foundry_admin", ROOT / "appliance/lib/foundry_admin.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FoundryAdministratorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state = Path(self.temporary.name)
        self.secret = self.state / "elderbrain/secrets/foundry-config.json"
        self.secret.parent.mkdir(parents=True)
        self.words = ROOT / "setup/shared/bootstrap-words.json"

    def operate(self, operation):
        with patch.object(MODULE, "STATE", self.state), patch.object(MODULE, "WORDLIST", self.words), patch.object(MODULE.os, "chown"):
            return MODULE.access_key(operation)

    def test_ensure_generates_four_words_and_preserves_download_credentials(self):
        self.secret.write_text(json.dumps({"foundry_username": "owner", "foundry_password": "private"}))
        result = self.operate("ensure")
        self.assertTrue(result["managed"])
        self.assertEqual(len(result["accessKey"].split("-")), 4)
        saved = json.loads(self.secret.read_text())
        self.assertEqual(saved["foundry_username"], "owner")
        self.assertEqual(saved["foundry_password"], "private")
        self.assertEqual(saved["foundry_admin_key"], result["accessKey"])
        self.assertEqual(self.secret.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.operate("status"), result)

    def test_existing_unmanaged_key_requires_explicit_reset(self):
        admin = self.state / "foundry/Config/admin.txt"
        admin.parent.mkdir(parents=True)
        admin.write_text("one-way-hash")
        self.assertEqual(self.operate("ensure"), {"managed": False, "resetRequired": True})
        self.assertFalse(self.secret.exists())
        reset = self.operate("reset")
        self.assertTrue(reset["managed"])
        self.assertFalse(admin.exists())
        self.assertEqual(json.loads(self.secret.read_text())["foundry_admin_key"], reset["accessKey"])

    def test_reset_rotates_an_existing_managed_key(self):
        self.secret.write_text(json.dumps({"foundry_admin_key": "amber-cabin-maple-river"}))
        admin = self.state / "foundry/Config/admin.txt"
        admin.parent.mkdir(parents=True)
        admin.write_text("one-way-hash")
        result = self.operate("reset")
        self.assertNotEqual(result["accessKey"], "amber-cabin-maple-river")
        self.assertFalse(admin.exists())

    def test_does_not_display_a_managed_key_changed_inside_foundry(self):
        key = "amber-cabin-maple-river"
        self.secret.write_text(json.dumps({"foundry_admin_key": key}))
        admin = self.state / "foundry/Config/admin.txt"
        admin.parent.mkdir(parents=True)
        admin.write_text(hashlib.pbkdf2_hmac(
            "sha512", key.encode(), b"17c4f39053ac5a50d5797c665ad1f4e6", 1000, 64).hex())
        self.assertTrue(self.operate("status")["managed"])
        admin.write_text("changed-in-foundry")
        self.assertEqual(self.operate("status"), {"managed": False, "resetRequired": True})

    def test_rejects_symlinked_administrator_file(self):
        admin = self.state / "foundry/Config/admin.txt"
        admin.parent.mkdir(parents=True)
        admin.symlink_to(self.secret)
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            self.operate("reset")


if __name__ == "__main__":
    unittest.main()
