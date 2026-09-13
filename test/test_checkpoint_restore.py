from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'appliance/lib'))
from backup_service import Maintenance
import checkpoint_restore
from checkpoint_staging import DEFAULT_CONFIG
from restore_service import recover_host
from restore_transaction import RestoreTransaction


class CheckpointRestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.identifier = 'a' * 32
        self.checkpoint = self.state / 'snapshots' / self.identifier
        self.live = self.state / 'elderbrain/config.json'
        self.live.parent.mkdir()
        (self.checkpoint / 'elderbrain').mkdir(parents=True)
        self.live.write_text(json.dumps({**DEFAULT_CONFIG, 'configured': True, 'domain': 'current.local'}))
        (self.checkpoint / 'elderbrain/config.json').write_text(json.dumps({**DEFAULT_CONFIG, 'domain': 'archived.local'}))
        self.events = []
        self.reject_new = False
        self.maintenance = Maintenance(self.state / 'maintenance', self)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        compatibility = {'schema': 1, 'applianceVersion': 'test', 'composeSha256': 'a' * 64, 'images': {}}
        self.store = self.stack.enter_context(patch('checkpoint_restore.Snapshots')).return_value
        self.store.root = self.state / 'snapshots'
        self.store.list.return_value = [{'id': self.identifier, 'compatibility': compatibility}]
        self.stack.enter_context(patch('checkpoint_restore.capture', return_value=compatibility))
        self.stack.enter_context(patch('checkpoint_restore.persistent_identity', return_value={'data_uuid': 'fixture'}))
        self.stack.enter_context(patch('restore_service.persistent_identity', return_value={'data_uuid': 'fixture'}))
        self.stack.enter_context(patch('host_bindings.refresh'))
        self.hooks = {'before_restore': lambda record: self.events.append('checkpoint'),
                      'release_checkpoint': lambda record: self.events.append('release')}
        self.stack.enter_context(patch('checkpoint_restore.checkpoint_hooks', return_value=self.hooks))
        self.stack.enter_context(patch('checkpoint_restore.create_backup', return_value={'archive': 'verified-fixture'}))

    def snapshot(self):
        return {'compose': [], 'graphics': False}

    def stop(self, saved):
        self.events.append('stop')

    def validate(self):
        self.events.append('validate')

    def resume_restored(self, saved):
        self.events.append('resume')
        if self.reject_new and json.loads(self.live.read_text())['domain'] == 'archived.local':
            raise RuntimeError('unhealthy')

    def restore(self):
        return checkpoint_restore.restore(self.identifier, ['preferences'], self.state, self.state,
                                          self.maintenance, host_root=self.state)

    def test_selected_preferences_activate_after_stop_and_preserve_other_state(self):
        original = checkpoint_restore.stage
        def stage(*args):
            self.assertEqual(self.events, ['stop'])
            self.store.pin.assert_called_once()
            self.assertEqual(self.store.list.call_count, 2)
            return original(*args)
        with patch('checkpoint_restore.stage', side_effect=stage):
            result = self.restore()
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['sourceCheckpoint'], self.identifier)
        value = json.loads(self.live.read_text())
        self.assertEqual(value['domain'], 'archived.local')
        self.assertTrue(value['configured'])
        self.assertIn('foundry.archived.local', (self.state / 'traefik/dynamic/lan-routes.yaml').read_text())
        self.assertEqual(self.events, ['stop', 'checkpoint', 'validate', 'resume', 'release'])
        self.assertEqual(list(self.maintenance.directory.glob('checkpoint-restore-*')), [])

    def test_unhealthy_activation_rolls_back_only_selected_targets(self):
        self.reject_new = True
        with self.assertRaisesRegex(RuntimeError, 'unhealthy'):
            self.restore()
        self.assertEqual(json.loads(self.live.read_text())['domain'], 'current.local')
        self.assertEqual(self.maintenance.previous()['state'], 'rolled-back')
        self.assertIn('foundry.current.local', (self.state / 'traefik/dynamic/lan-routes.yaml').read_text())
        self.assertEqual(self.events[-1], 'release')

    def test_missing_compatibility_rejected_before_stop(self):
        self.store.list.return_value = [{'id': self.identifier}]
        with self.assertRaises(ValueError):
            self.restore()
        self.assertEqual(self.events, [])
        self.store.pin.assert_not_called()

    def test_process_loss_recovers_using_fixed_host_targets(self):
        original = RestoreTransaction.apply
        def crash(transaction):
            original(transaction)
            raise SystemExit('power loss')
        with patch.object(RestoreTransaction, 'apply', crash):
            with self.assertRaises(SystemExit):
                self.restore()
        self.assertEqual(json.loads(self.live.read_text())['domain'], 'archived.local')
        with patch('restore_service.persistent_identity', return_value=None):
            result = recover_host(self.state, self.state, self.maintenance, host_root=self.state)
        self.assertEqual(result['state'], 'rolled-back')
        self.assertEqual(json.loads(self.live.read_text())['domain'], 'current.local')
        self.assertIn('foundry.current.local', (self.state / 'traefik/dynamic/lan-routes.yaml').read_text())


if __name__ == '__main__':
    unittest.main()
