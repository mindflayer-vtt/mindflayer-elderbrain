from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'appliance/lib'))
from local_snapshots import Snapshots, validate_nested, retention_candidates, validate_pin, validate_retention


class SnapshotTests(unittest.TestCase):
    def test_retention_settings_validation(self):
        self.assertEqual(validate_retention({'enabled': True, 'keep': 3}), {'enabled': True, 'keep': 3})
        for value in (None, {}, {'enabled': 1, 'keep': 3}, {'enabled': True, 'keep': True},
                      {'enabled': True, 'keep': 0}, {'enabled': True, 'keep': 1001},
                      {'enabled': True, 'keep': 3, 'extra': 1}):
            with self.assertRaises(ValueError):
                validate_retention(value)

    def test_pin_identity_and_purpose_validation(self):
        validate_pin('a' * 32, 'b' * 32, 'pending-backup')
        for identifier, owner, purpose in [(None, 'b' * 32, 'update'),
                                            ('a' * 32, '../owner', 'restore'),
                                            ('a' * 32, 'b' * 32, 'unknown')]:
            with self.assertRaises(ValueError):
                validate_pin(identifier, owner, purpose)
        with tempfile.TemporaryDirectory() as directory:
            store = Snapshots(directory, guard=lambda: None, quiesce=None)
            with self.assertRaises(ValueError):
                store.create('before-update', owner='b' * 32)
            self.assertFalse(store.root.exists())

    def test_retention_keeps_newest_and_active_pins(self):
        records = [{'id': str(index) * 32, 'createdAt': index} for index in range(1, 5)]
        self.assertEqual(retention_candidates(records, 2), ['1' * 32, '2' * 32])
        self.assertEqual(retention_candidates(records, 1, ['1' * 32, '3' * 32]), ['2' * 32])
        for keep in (0, -1, True, 1001, '2'):
            with self.assertRaises(ValueError):
                retention_candidates(records, keep)
        with self.assertRaises(ValueError):
            retention_candidates(records, 1, ['../user-data'])

    def test_nested_data_never_silently_omitted(self):
        validate_nested('')
        validate_nested('ID 256 gen 5 top level 5 path snapshots/' + 'a' * 32)
        for value in ('unexpected format', 'ID 256 gen 5 top level 5 path foundry/worlds',
                      'ID 256 gen 5 top level 5 path snapshots/../../foundry'):
            with self.assertRaises(ValueError):
                validate_nested(value)

    def test_capture_quiesces_and_checks_readonly_before_completion(self):
        events = []
        @contextmanager
        def quiesce():
            events.append('stop')
            try:
                yield
            finally:
                events.append('resume')
        def run(args, **kwargs):
            self.assertEqual(events[-1], 'stop')
            if args[:3] == ['btrfs', 'subvolume', 'snapshot']:
                self.assertEqual(args[3], '-r')
                Path(args[-1]).mkdir()
            return SimpleNamespace(stdout='ro=true' if args[:2] == ['btrfs', 'property'] else '')
        with tempfile.TemporaryDirectory() as directory:
            store = Snapshots(directory, guard=lambda: None, quiesce=quiesce, run=run)
            # Root ownership is verified by real guest tests; local test runs unprivileged.
            def prepare():
                store.root.mkdir(mode=0o700)
            with patch.object(store, 'prepare', prepare):
                result = store.create('manual')
            self.assertEqual(events, ['stop', 'resume'])
            self.assertTrue((store.root / (result['id'] + '.json')).is_file())

    def test_failed_snapshot_always_resumes_and_does_not_publish_metadata(self):
        events = []
        @contextmanager
        def quiesce():
            try:
                yield
            finally:
                events.append('resume')
        def run(args, **kwargs):
            if args[:3] == ['btrfs', 'subvolume', 'snapshot']:
                raise RuntimeError('fixture failure')
            return SimpleNamespace(stdout='')
        with tempfile.TemporaryDirectory() as directory:
            store = Snapshots(directory, guard=lambda: None, quiesce=quiesce, run=run)
            with patch.object(store, 'prepare', lambda: store.root.mkdir(mode=0o700)):
                with self.assertRaises(RuntimeError):
                    store.create('before-update')
            self.assertEqual(events, ['resume'])
            self.assertEqual(list(store.root.glob('*.json')), [])
