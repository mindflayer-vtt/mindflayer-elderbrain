from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'appliance/lib'))
from backup_service import Maintenance, save_record
from network_checkpoint_restore import NetworkCheckpointRestore, coordinator
from network_transaction import NetworkTransaction


class NetworkCheckpointRestoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.events = []
        self.exclusive_held = False
        self.identifier = 'a' * 32
        archived = self.root / 'snapshots' / self.identifier / 'host/netplan'
        archived.mkdir(parents=True)
        (archived / '50-network.yaml').write_bytes(b'archived-private')
        netplan = self.root / 'netplan'
        netplan.mkdir()
        (netplan / '50-network.yaml').write_bytes(b'current-private')
        self.network = NetworkTransaction(self.root / 'network', netplan,
                                          apply=lambda: None, verify_confirmation=lambda *_: True)
        self.snapshots = Mock(root=self.root / 'snapshots')
        self.snapshots.create.side_effect = self.capture
        self.maintenance = Maintenance(self.root / 'maintenance', self)
        self.compatible = Mock()
        self.coordinator = NetworkCheckpointRestore(self.maintenance, self.snapshots, self.network,
            compatible=self.compatible, exclusive=self.exclusive, stage=self.stage)
        self.network.on_terminal = self.coordinator.finalize

    def snapshot(self):
        return {'compose': [], 'graphics': False}

    def stop(self, saved):
        self.assertTrue(self.exclusive_held)
        self.events.append('stop')

    def resume(self, saved):
        self.assertFalse(self.exclusive_held)
        self.events.append('resume')

    @contextmanager
    def exclusive(self):
        self.exclusive_held = True
        try:
            yield
        finally:
            self.exclusive_held = False

    def capture(self, *args, **kwargs):
        self.assertTrue(self.exclusive_held)
        self.snapshots.pin.assert_called_once()
        self.events.append('checkpoint')
        return {'id': 'b' * 32}

    def stage(self, archived, interface, *, restore_owner):
        self.assertEqual(self.events[-1], 'resume')
        self.assertEqual(self.maintenance.previous()['state'], 'awaiting-network')
        self.events.append('stage')
        result = self.network.stage({'50-network.yaml': {
            'before': b'current-private', 'after': archived['50-network.yaml']}},
            interface, restore_owner=restore_owner)
        return {**result, 'token': 'private-one-time-token'}

    def start(self):
        return self.coordinator.start(self.identifier, 'ens3')

    def test_handoff_keeps_pins_and_maintenance_until_rollback(self):
        result = self.start()
        self.assertEqual(self.events, ['stop', 'checkpoint', 'resume', 'stage'])
        self.snapshots.unpin_owner.assert_not_called()
        self.assertEqual(self.compatible.call_count, 2)
        journal = self.maintenance.journal.read_text()
        self.assertNotIn('private', journal)
        with self.assertRaises(RuntimeError):
            self.coordinator.recover()
        self.network.cancel(result['id'])
        self.assertEqual(self.maintenance.previous()['state'], 'rolled-back')
        self.snapshots.unpin_owner.assert_called_once_with(self.maintenance.previous()['id'], 'restore')
        self.assertTrue(self.network.read()['cleanupComplete'])
        with patch.object(self.network, 'write') as write:
            self.network.finalize()
            write.assert_not_called()

    def test_completed_network_restore_releases_without_service_calls(self):
        self.start()
        with self.network.locked():
            record = self.network.read()
            record['phase'] = 'confirmed'
            self.network.write(record)
        self.events.clear()
        self.network.finalize()
        self.assertEqual(self.events, [])
        self.assertEqual(self.maintenance.previous()['state'], 'completed')

    def test_stage_failure_after_durable_write_keeps_owner(self):
        def fail(*args, **kwargs):
            self.stage(*args, **kwargs)
            raise RuntimeError('lost response')
        self.coordinator.stage = fail
        with self.assertRaises(RuntimeError):
            self.start()
        self.assertEqual(self.maintenance.previous()['state'], 'awaiting-network')
        self.snapshots.unpin_owner.assert_not_called()
        self.network.cancel(self.network.read()['id'])
        self.assertEqual(self.maintenance.previous()['state'], 'rolled-back')

    def test_process_loss_before_handoff_recovers_pins_and_services(self):
        self.snapshots.create.side_effect = SystemExit('process loss')
        with self.assertRaises(SystemExit):
            self.start()
        self.snapshots.unpin_owner.assert_not_called()
        self.assertEqual(self.coordinator.recover()['state'], 'rolled-back')
        self.assertEqual(self.events, ['stop', 'resume'])
        self.snapshots.unpin_owner.assert_called_once()

    def test_process_loss_after_handoff_leaves_timed_worker_in_charge(self):
        def die(*args, **kwargs):
            self.stage(*args, **kwargs)
            raise SystemExit('process loss')
        self.coordinator.stage = die
        with self.assertRaises(SystemExit):
            self.start()
        self.snapshots.unpin_owner.assert_not_called()
        self.network.recover_boot(lambda: None)
        self.assertEqual(self.maintenance.previous()['state'], 'rolled-back')

    def test_failure_before_staging_resumes_services_and_releases_pins(self):
        self.coordinator.stage = Mock(side_effect=ValueError('invalid candidate'))
        with self.assertRaisesRegex(ValueError, 'invalid candidate'):
            self.start()
        self.assertIsNone(self.network.read())
        self.assertEqual(self.maintenance.previous()['state'], 'rolled-back')
        self.snapshots.unpin_owner.assert_called_once()

    def test_service_resume_failure_never_hands_off_network_or_unpins(self):
        self.resume = Mock(side_effect=RuntimeError('service failure'))
        with self.assertRaisesRegex(RuntimeError, 'service failure'):
            self.start()
        self.assertIsNone(self.network.read())
        self.assertEqual(self.maintenance.previous()['state'], 'starting')
        self.snapshots.unpin_owner.assert_not_called()

    def test_cleanup_failure_blocks_new_maintenance_and_retries(self):
        result = self.start()
        self.snapshots.unpin_owner.side_effect = RuntimeError('storage unavailable')
        with self.assertRaises(RuntimeError):
            self.network.cancel(result['id'])
        self.assertEqual(self.maintenance.previous()['state'], 'awaiting-network')
        self.assertNotIn('cleanupComplete', self.network.read())
        with self.assertRaises(RuntimeError):
            self.start()
        self.snapshots.unpin_owner.side_effect = None
        self.network.finalize()
        self.assertEqual(self.maintenance.previous()['state'], 'rolled-back')

    def test_receipt_allows_cleanup_retry_after_maintenance_reuse(self):
        result = self.start()
        self.network.cancel(result['id'])
        record = self.network.read()
        save_record(self.maintenance.journal, {'operation': 'backup', 'id': 'c' * 32, 'state': 'completed'})
        self.coordinator.finalize(record)
        self.assertEqual(self.maintenance.previous()['operation'], 'backup')
        with self.assertRaisesRegex(RuntimeError, 'receipt mismatch'):
            self.coordinator.finalize({**record, 'id': 'd' * 32})

    def test_incompatible_checkpoint_rejected_before_service_stop(self):
        self.compatible.side_effect = ValueError('incompatible')
        with self.assertRaises(ValueError):
            self.start()
        self.assertEqual(self.events, [])
        self.assertEqual(self.maintenance.previous(), {})

    def test_generic_recovery_cannot_bypass_network_coordinator(self):
        self.start()
        with self.assertRaises(RuntimeError):
            self.maintenance.recover()
        self.snapshots.unpin_owner.assert_not_called()

    def test_early_boot_callback_rejects_handoff_before_services_resumed(self):
        self.start()
        record = self.network.read()
        record['phase'] = 'rolled-back'
        self.network.write(record)
        maintenance = self.maintenance.previous()
        maintenance['state'] = 'starting'
        save_record(self.maintenance.journal, maintenance)
        self.events.clear()
        with self.assertRaisesRegex(RuntimeError, 'not resumed'):
            self.coordinator.finalize(record)
        self.assertEqual(self.events, [])
        self.snapshots.unpin_owner.assert_not_called()

    def test_production_factory_rejects_unverified_storage(self):
        with patch('restore_service.persistent_identity', return_value=None):
            with self.assertRaisesRegex(ValueError, 'verified persistent storage'):
                coordinator(self.root, self.root)

    def test_production_compatibility_rechecks_storage_before_stop(self):
        with patch('restore_service.persistent_identity', side_effect=[{'data_uuid': 'one'}, {'data_uuid': 'two'}]):
            host = coordinator(self.root, self.root, maintenance=self.maintenance, network=self.network)
            with self.assertRaisesRegex(ValueError, 'storage changed'):
                host.start(self.identifier, 'ens3')
        self.assertEqual(self.events, [])


if __name__ == '__main__':
    unittest.main()
