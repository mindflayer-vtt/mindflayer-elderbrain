import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('network_staging', ROOT / 'appliance/lib/network_staging.py')
module = importlib.util.module_from_spec(spec)
with patch.object(sys, 'path', [str(ROOT / 'appliance/lib'), *sys.path]):
    spec.loader.exec_module(module)


class NetworkStagingTests(unittest.TestCase):
    def test_restore_stages_complete_file_set_and_preserves_live_sources(self):
        before = self.source.read_bytes()
        vendor = self.root / 'lib/netplan/10-vendor.yaml'
        vendor.parent.mkdir(parents=True)
        vendor.write_text('network: {version: 2}')
        def validate(root, operation):
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            self.assertFalse((root / 'etc/netplan/50-source.yaml').exists())
            self.assertEqual((root / 'etc/netplan/70-archived.yaml').read_bytes(), before)
            self.assertEqual((root / 'etc/netplan/70-archived.yaml').stat().st_mode & 0o777, 0o600)
            self.assertEqual((root / 'lib/netplan/10-vendor.yaml').read_bytes(), vendor.read_bytes())
            return {'network': {'version': 2}} if operation == 'get' else None
        result = module.prepare_restore({'70-archived.yaml': before}, self.root, validate=validate)
        self.assertEqual(result['changes'], {'50-source.yaml': {'before': before, 'after': None},
                                            '70-archived.yaml': {'before': None, 'after': before}})
        self.assertEqual(self.source.read_bytes(), before)
        self.assertFalse((self.source.parent / '70-archived.yaml').exists())

    def test_restore_rejects_paths_invalid_bytes_and_concurrent_changes(self):
        for archived in ({}, {'../escape.yaml': b''}, {'x.yaml': 'text'}, {'x.yaml': b'x' * (2 * 1024 * 1024 + 1)}):
            with self.assertRaises(ValueError):
                module.prepare_restore(archived, self.root, validate=self.validate)
        def validate(root, operation):
            self.source.chmod(0o640)
            return {}
        with self.assertRaisesRegex(ValueError, 'changed during'):
            module.prepare_restore({'70-archived.yaml': b'network: {version: 2}'}, self.root, validate=validate)

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / 'etc/netplan/50-source.yaml'
        self.source.parent.mkdir(parents=True)
        self.source.write_text('network:\n  version: 2\n  ethernets:\n    ens3:\n      dhcp4: true\n')
        self.source.chmod(0o600)
        self.values = {'interface': 'ens3', 'mode': 'static', 'address': '10.0.2.20', 'prefix': 24, 'gateway': '', 'dns': []}

    def validate(self, root, operation):
        self.assertNotEqual(root, self.root)
        self.assertEqual(os.stat(root).st_mode & 0o777, 0o700)
        return yaml.safe_load((root / 'etc/netplan/50-source.yaml').read_text()) if operation == 'get' else None

    def test_isolated_validation_never_writes_original(self):
        before = self.source.read_bytes()
        result = module.prepare(self.values, self.root, validate=self.validate)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(result['changes']['50-source.yaml']['before'], before)
        self.assertEqual(result['fingerprint'], module.fingerprint(module.snapshot(self.root)))
        self.assertNotIn('configuration', result)

    def test_concurrent_new_file_and_metadata_changes_invalidate_snapshot(self):
        def validate(root, operation):
            if operation == 'generate':
                (self.source.parent / '90-new.yaml').write_text('network: {version: 2}')
            return self.validate(root, operation)
        with self.assertRaisesRegex(ValueError, 'changed during'):
            module.prepare(self.values, self.root, validate=validate)
        first = module.fingerprint(module.snapshot(self.root))
        self.source.chmod(0o640)
        self.assertNotEqual(first, module.fingerprint(module.snapshot(self.root)))

    def test_wrong_merged_result_is_rejected(self):
        calls = 0
        def validate(root, operation):
            nonlocal calls
            calls += 1
            return {} if calls == 3 else self.validate(root, operation)
        with self.assertRaisesRegex(ValueError, 'differs'):
            module.prepare(self.values, self.root, validate=validate)

    def test_symlink_and_fifo_sources_fail_closed(self):
        link = self.source.parent / 'linked.yaml'
        link.symlink_to(self.source)
        with self.assertRaises(OSError):
            module.snapshot(self.root)
        link.unlink()
        os.mkfifo(link, 0o600)
        with self.assertRaises(ValueError):
            module.snapshot(self.root)
