import base64
import fnmatch
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "appliance/lib"))
from borg_settings import BorgSettings
from backup_service import save_record


class BorgSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = BorgSettings(self.temp.name)
        self.nfs = {"kind": "nfs", "host": "nas.example.com", "export": "/exports/backups", "repository": "elderbrain"}
        self.ssh = {"kind": "ssh", "host": "backup.example.com", "user": "borg", "port": 2222,
                    "repository": "/backups/elderbrain", "hostKey": "ssh-ed25519 " + base64.b64encode(b"x" * 32).decode()}

    def test_settings_generate_private_passphrase_and_redact_it(self):
        result = self.settings.configure(self.nfs)
        self.assertTrue(result["passphraseStored"])
        self.assertNotIn("passphrase", result)
        private = self.settings.read()["passphrase"]
        self.assertGreaterEqual(len(private), 32)
        self.assertEqual(self.settings.file.stat().st_mode & 0o777, 0o600)
        self.settings.configure({**self.nfs, "schedule": "04:12"})
        self.assertEqual(self.settings.read()["passphrase"], private)
        self.assertIn("OnCalendar=*-*-* 04:12:00", self.settings.timer())

    def test_ssh_config_enforces_host_key_check_and_no_arbitrary_commands(self):
        self.settings.configure(self.ssh)
        config = self.settings.render(self.settings.read(), "appliance-id")
        self.assertEqual(config["repositories"][0]["path"], "ssh://borg@backup.example.com:2222/backups/elderbrain")
        self.assertIn("StrictHostKeyChecking=yes", config["ssh_command"])
        self.assertIn("BatchMode=yes", config["ssh_command"])
        self.assertNotIn("before_backup", config)

    def test_rejects_injection_and_invalid_paths(self):
        for update in ({"host": "$(whoami)"}, {"repository": "../escape"}, {"export": "/"},
                       {"repository": "repo/{hostname}"}, {"schedule": "03:00\nExecStart=evil"},
                       {"retention": {"daily": 0, "weekly": 4, "monthly": 6}}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.settings.configure({**self.nfs, **update})
        for update in ({"hostKey": ""}, {"user": "-oProxyCommand=evil"}, {"port": True}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.settings.configure({**self.ssh, **update})

    def test_retention_matches_old_versions_but_not_other_appliances(self):
        self.settings.configure(self.nfs)
        config = self.settings.render(self.settings.read(), "table-one", "2.0.0")
        self.assertTrue(config["match_archives"].startswith("sh:"))
        pattern = config["match_archives"].removeprefix("sh:")
        self.assertTrue(fnmatch.fnmatchcase("elderbrain-table-one--1.0.0--2026-09-01", pattern))
        self.assertTrue(fnmatch.fnmatchcase("elderbrain-table-one--2.0.0--2026-09-10", pattern))
        self.assertFalse(fnmatch.fnmatchcase("elderbrain-table-two--2.0.0--2026-09-10", pattern))

    @unittest.skipUnless(os.environ.get("ELDERBRAIN_TEST_BORGMATIC"), "requires isolated Borgmatic executable")
    def test_generated_config_passes_real_borgmatic_schema(self):
        for settings in (self.nfs, self.ssh):
            self.settings.configure(settings)
            config = self.settings.directory / "borgmatic.yaml"
            save_record(config, self.settings.render(self.settings.read(), "test-appliance"))
            result = subprocess.run([os.environ["ELDERBRAIN_TEST_BORGMATIC"], "--config", str(config), "config", "validate"],
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
