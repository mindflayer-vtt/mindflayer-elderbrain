import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test.test_appliance_release as fixture
from provisioning.update_trust import provision


class UpdateTrustTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.ApplianceReleaseTests.setUpClass()
        cls.addClassCleanup(fixture.ApplianceReleaseTests.doClassCleanups)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'host'
        self.payload = Path(temporary.name) / 'payload'
        for path in ('etc/elderbrain', 'var/lib', 'usr/lib'):
            (self.root / path).mkdir(parents=True)
        self.config = self.payload / 'config/private'
        self.config.mkdir(parents=True)
        (self.payload / 'release').mkdir()
        (self.payload / 'release/host-files.json').write_text(json.dumps([
            {'source': 'appliance/lib/host_jobs.py', 'path': 'runtime/host_jobs.py', 'mode': 420}]))
        self.storage = self.enterContext(patch('provisioning.update_trust.persistent_identity', return_value='verified'))

    def configure(self):
        (self.config / 'release-source.json').write_text('{"baseUrl":"https://updates.example.test/stable/"}')
        (self.config / 'release-public.pem').write_bytes(fixture.ApplianceReleaseTests.public.read_bytes())

    def run_provision(self):
        return provision(payload=self.payload, host_root=self.root)

    def test_optional_configuration_does_not_create_update_storage(self):
        self.assertEqual(self.run_provision()['state'], 'not-configured')
        self.assertFalse((self.root / 'var/lib/elderbrain-releases').exists())

    def test_explicit_public_trust_is_installed_idempotently(self):
        self.configure()
        self.assertEqual(self.run_provision()['state'], 'configured')
        self.assertEqual(self.run_provision()['state'], 'configured')
        target = self.root / 'etc/elderbrain/release-public.pem'
        self.assertEqual(target.read_bytes(), fixture.ApplianceReleaseTests.public.read_bytes())
        self.assertEqual(target.stat().st_mode & 0o777, 0o644)
        self.assertEqual((self.root / 'var/lib/elderbrain-releases/prepared').stat().st_mode & 0o777, 0o700)

    def test_private_key_missing_storage_and_changed_trust_fail_closed(self):
        self.configure()
        key = self.config / 'release-public.pem'
        key.write_bytes(fixture.ApplianceReleaseTests.private.read_bytes())
        with self.assertRaisesRegex(ValueError, 'public release key'):
            self.run_provision()
        self.configure()
        self.storage.return_value = None
        with self.assertRaisesRegex(ValueError, 'persistent storage'):
            self.run_provision()
        self.storage.return_value = 'verified'
        self.run_provision()
        target = self.root / 'etc/elderbrain/release-source.json'
        before = target.read_bytes()
        (self.config / 'release-source.json').write_text('{"baseUrl":"https://other.example.test/"}')
        with self.assertRaisesRegex(ValueError, 'explicit migration'):
            self.run_provision()
        self.assertEqual(target.read_bytes(), before)
