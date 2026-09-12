import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('storage_guard', ROOT / 'appliance/lib/storage_guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class StorageGuardTests(unittest.TestCase):
    def setUp(self):
        self.identity = dict(product='mindflayer-elderbrain', layout_version=1,
                             data_uuid='4229266e-c564-4bd5-b2db-f4433b5572c5',
                             appliance_id='fb7e5cae-d530-4a1b-9138-322ad8fa48d1',
                             disk_serial='test-disk')
        self.mount = dict(target=guard.DATA_MOUNT, fstype='btrfs', fsroot='/',
                          uuid=self.identity['data_uuid'], options='rw,relatime,subvolid=5')

    def verify(self):
        guard.verify_mount({'filesystems': [self.mount]}, self.identity, self.identity)

    def test_expected_volume_is_accepted(self):
        self.verify()

    def test_wrong_mounts_and_readonly_fail_closed(self):
        for key, value in [('target', '/'), ('fstype', 'ext4'), ('uuid', 'different'),
                           ('fsroot', '/snapshot'), ('options', 'ro,relatime'),
                           ('options', '')]:
            original = self.mount[key]
            self.mount[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify()
            self.mount[key] = original

    def test_missing_or_stacked_mounts_are_rejected(self):
        for mounts in (None, [], [self.mount, self.mount]):
            with self.assertRaises(ValueError):
                guard.verify_mount({'filesystems': mounts}, self.identity, self.identity)

    def test_other_appliance_marker_rejected(self):
        other = copy.deepcopy(self.identity)
        other['disk_serial'] = 'other-disk'
        with self.assertRaises(ValueError):
            guard.verify_mount({'filesystems': [self.mount]}, self.identity, other)

    def test_bad_mount_is_rejected_before_marker_read(self):
        read = Mock(return_value=self.identity)
        run = Mock(return_value=SimpleNamespace(stdout=json.dumps({'filesystems': []})))
        with self.assertRaises(ValueError):
            guard.check(run=run, read=read)
        self.assertEqual(read.call_count, 1)
        self.assertIn('--mountpoint', run.call_args.args[0])

    def test_identity_schema_and_canonical_uuids_required(self):
        for key, value in [('layout_version', True), ('layout_version', 2),
                           ('product', 'other'), ('disk_serial', ''),
                           ('data_uuid', 'invalid'), ('appliance_id', None)]:
            identity = {**self.identity, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError):
                guard.validate_identity(identity)


if __name__ == '__main__':
    unittest.main()
