import hashlib
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'appliance/lib'))
from release_checkpoints import UpdateCheckpoints
from restore_transaction import RestoreTransaction


class UpdateCheckpointTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.runtime = self.root / 'runtime'
        self.runtime.mkdir()
        (self.runtime / 'VERSION').write_text('1.0.0\n')
        (self.runtime / 'compose.yaml').write_text('old compose')
        self.state = self.root / 'state'
        self.state.mkdir()
        self.maintenance = SimpleNamespace(directory=self.state / 'maintenance')
        self.maintenance.directory.mkdir()
        identity = patch('release_checkpoints.persistent_identity', return_value={'data_uuid': 'fixture'})
        self.identity = identity.start()
        self.addCleanup(identity.stop)
        self.adapter = UpdateCheckpoints(self.state, self.runtime, self.maintenance)
        self.adapter.refresh = Mock()
        self.store = self.adapter.snapshots = Mock()
        self.store.root = self.state / 'snapshots'
        self.record = {'id': 'a' * 32, 'rollbackCheckpoint': 'b' * 32}
        self.store.create.return_value = {'id': 'b' * 32}
        metadata = {'schema': 1, 'applianceVersion': '1.0.0',
                    'composeSha256': hashlib.sha256(b'old compose').hexdigest(), 'images': {}}
        self.store.list.return_value = [{'id': 'b' * 32, 'reason': 'before-update', 'compatibility': metadata}]
        for name, target in self.adapter.targets().items():
            target.mkdir(parents=True)
            (target / 'value').write_text('changed by new runtime')
            archived = self.store.root / ('b' * 32) / name
            archived.mkdir(parents=True)
            (archived / 'value').write_text('before update')
        (self.maintenance.directory / 'keep').write_text('control-plane journal')

    def test_capture_and_release_use_operation_owned_update_pin(self):
        self.adapter.checkpoint(self.record)
        self.store.create.assert_called_once_with('before-update', owner='a' * 32, purpose='update')
        with self.assertRaisesRegex(ValueError, 'unfinished'):
            self.adapter.release(self.record)
        self.record['state'] = 'completed'
        del self.record['rollbackCheckpoint']
        self.adapter.release(self.record)
        self.store.unpin_owner.assert_called_once_with('a' * 32, 'update')

    def test_data_restoration_preserves_control_plane_and_is_repeatable(self):
        self.adapter.restore(self.record)
        for target in self.adapter.targets().values():
            self.assertEqual((target / 'value').read_text(), 'before update')
        self.assertEqual((self.maintenance.directory / 'keep').read_text(), 'control-plane journal')
        self.adapter.restore(self.record)
        self.assertEqual(self.adapter.refresh.call_count, 2)
        self.store.unpin_owner.assert_not_called()

    def test_interrupted_data_switch_is_reversed_then_retried(self):
        apply = RestoreTransaction.apply
        def crash(transaction):
            apply(transaction)
            raise SystemExit('power loss before checkpoint restore commit')
        with patch.object(RestoreTransaction, 'apply', crash):
            with self.assertRaises(SystemExit):
                self.adapter.restore(self.record)
        self.adapter.restore(self.record)
        for target in self.adapter.targets().values():
            self.assertEqual((target / 'value').read_text(), 'before update')
        self.assertEqual(len(list(self.maintenance.directory.glob('*-attempt-*.json'))), 1)

    def test_wrong_runtime_or_missing_scope_rejected_before_replacement(self):
        (self.runtime / 'VERSION').write_text('2.0.0')
        with self.assertRaisesRegex(ValueError, 'previous runtime'):
            self.adapter.restore(self.record)
        self.assertFalse(list(self.maintenance.directory.glob('update-data-*.json')))
        (self.runtime / 'VERSION').write_text('1.0.0')
        source = self.store.root / ('b' * 32) / 'foundry'
        (source / 'value').unlink()
        source.rmdir()
        with self.assertRaisesRegex(ValueError, 'scope'):
            self.adapter.restore(self.record)

    def test_changed_storage_rejected_before_snapshot_activity(self):
        self.identity.return_value = {'data_uuid': 'other'}
        with self.assertRaisesRegex(ValueError, 'storage changed'):
            self.adapter.checkpoint(self.record)
        self.store.create.assert_not_called()


if __name__ == '__main__':
    unittest.main()
