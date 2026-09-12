import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('beamer_runtime', ROOT / 'appliance/lib/beamer_runtime.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BeamerProjectionTests(unittest.TestCase):
    def test_username_projection_and_legacy_id_compatibility(self):
        value = {'version': 1, 'revision': 'a' * 32, 'worldId': 'world-one',
                 'username': 'Beamer', 'password': 'test-only-private-password'}
        self.assertEqual(module.credential(value), value)
        for name in ('', ' ', 'bad\nname', 'a' * 129):
            with self.assertRaises(ValueError):
                module.credential({**value, 'username': name})

    def test_status_requires_fresh_matching_revision_and_redacts_private_fields(self):
        value = {'updatedAt': 100, 'password': 'never-return', 'views': [
            {'index': 1, 'state': 'ready', 'revision': 'current', 'observedAt': 99, 'password': 'never-return'}]}
        self.assertEqual(module.public_status(value, 'current', 101), {'state': 'ready', 'views': [{'index': 1, 'state': 'ready'}]})
        self.assertEqual(module.public_status(value, 'new', 101)['state'], 'pending-verification')
        self.assertEqual(module.public_status(value, 'current', 120)['state'], 'unavailable')
        value['updatedAt'] = 120
        self.assertEqual(module.public_status(value, 'current', 120)['state'], 'unavailable')
        value['views'] = []
        self.assertEqual(module.public_status(value, 'current', 120)['state'], 'display-disconnected')

    def test_projection_permissions_and_revocation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.json'
            target = root / 'runtime'
            value = {'version': 1, 'revision': 'a' * 32, 'worldId': 'world-one',
                     'userId': '1234567890abcdef', 'password': 'test-only-private-password', 'unrelated': 'exclude'}
            source.write_text(json.dumps(value))
            source.chmod(0o600)
            result = module.refresh(source, target, os.getgid())
            self.assertNotIn(value['password'], json.dumps(result))
            projected = target / 'beamer.json'
            self.assertEqual(projected.stat().st_mode & 0o777, 0o640)
            self.assertNotIn('unrelated', json.loads(projected.read_text()))
            self.assertEqual(module.read_private(projected, owners=(os.getuid(),), mask=0o027)['revision'], value['revision'])
            source.unlink()
            self.assertEqual(module.refresh(source, target, os.getgid())['state'], 'pairing-required')
            self.assertFalse(projected.exists())

    def test_corruption_removes_stale_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'runtime'
            target.mkdir(mode=0o750)
            stale = target / 'beamer.json'
            stale.write_text('{}')
            source = root / 'source.json'
            source.write_text('private-malformed-secret')
            source.chmod(0o600)
            with self.assertRaisesRegex(ValueError, '^Beamer record unavailable$'):
                module.refresh(source, target, os.getgid())
            self.assertFalse(stale.exists())

    def test_unsafe_files_and_extra_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source'
            source.symlink_to('/etc/passwd')
            with self.assertRaises(OSError):
                module.read_private(source)
        for value in ({}, {'version': 1}, [], {'version': 1, 'password': 'private'}):
            with self.assertRaises(ValueError):
                module.credential(value)
