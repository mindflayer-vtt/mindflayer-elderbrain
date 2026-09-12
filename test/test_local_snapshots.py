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
    def test_owner_release_keeps_other_operations_and_checkpoint_data(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Snapshots(directory, guard=lambda: None, quiesce=None)
            store.root.mkdir(mode=0o700)
            owner = 'b' * 32
            pins = [
                {'id': 'a' * 32, 'owner': owner, 'purpose': 'restore'},
                {'id': 'c' * 32, 'owner': 'd' * 32, 'purpose': 'restore'},
                {'id': 'e' * 32, 'owner': owner, 'purpose': 'pending-backup'},
            ]
            for pin in pins:
                (store.root / (pin['id'] + '.' + pin['owner'] + '.pin')).touch()
                (store.root / pin['id']).mkdir()
            # Private ownership/format checking belongs to pins(); exercise the
            # release boundary and filesystem effects without requiring root.
            with patch.object(store, 'prepare'), patch.object(store, 'pins', return_value=pins):
                store.unpin_owner(owner, 'restore')
            self.assertFalse((store.root / ('a' * 32 + '.' + owner + '.pin')).exists())
            self.assertEqual(len(list(store.root.glob('*.pin'))), 2)
            self.assertTrue(all((store.root / pin['id']).is_dir() for pin in pins))
            with patch.object(store, 'prepare'), patch.object(store, 'pins', return_value=pins[1:]):
                store.unpin_owner(owner, 'restore')  # Recovery may repeat.

    def test_corrupt_pins_block_owner_release(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Snapshots(directory, guard=lambda: None, quiesce=None)
            store.root.mkdir(mode=0o700)
            pin = store.root / ('a' * 32 + '.' + 'b' * 32 + '.pin')
            pin.touch()
            with patch.object(store, 'prepare'), patch.object(store, 'pins', side_effect=ValueError('unsafe')):
                with self.assertRaises(ValueError):
                    store.unpin_owner('b' * 32, 'restore')
            self.assertTrue(pin.exists())

    def test_pinned_records_validates_pins_and_checkpoints_under_one_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Snapshots(directory, guard=lambda: None, quiesce=None)
            store.root.mkdir(mode=0o700)
            checkpoint = {'id': 'a' * 32, 'reason': 'before-shutdown', 'createdAt': 1}
            pin = {'id': checkpoint['id'], 'owner': 'b' * 32, 'purpose': 'pending-backup'}
            with patch.object(store, 'prepare'), patch.object(store, 'records', return_value=[checkpoint]), \
                    patch.object(store, 'pins', return_value=[pin]):
                self.assertEqual(store.pinned_records('pending-backup'), [
                    {'pin': pin, 'checkpoint': checkpoint}])
            with patch.object(store, 'prepare'), patch.object(store, 'records', return_value=[]), \
                    patch.object(store, 'pins', return_value=[pin]), self.assertRaisesRegex(ValueError, 'complete'):
                store.pinned_records('pending-backup')

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
            compatibility = {'schema': 1, 'applianceVersion': '1.0.0', 'composeSha256': 'a' * 64, 'images': {}}
            def capture():
                self.assertEqual(events, ['stop'])
                return compatibility
            store = Snapshots(directory, guard=lambda: None, quiesce=quiesce, run=run, compatibility=capture)
            # Root ownership is verified by real guest tests; local test runs unprivileged.
            def prepare():
                store.root.mkdir(mode=0o700)
            with patch.object(store, 'prepare', prepare):
                result = store.create('manual')
            self.assertEqual(events, ['stop', 'resume'])
            self.assertTrue((store.root / (result['id'] + '.json')).is_file())
            import json
            saved = json.loads((store.root / (result['id'] + '.json')).read_text())
            self.assertEqual(saved['compatibility'], compatibility)

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
