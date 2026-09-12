from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import test.test_release_baseline
from backup_service import Maintenance
from release_baseline_install import Migration
from restore_transaction import RestoreTransaction


class MigrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.runtime = self.root / 'opt/mindflayer-elderbrain'
        self.runtime.mkdir(parents=True)
        self.units = self.root / 'etc/systemd/system'
        self.units.mkdir(parents=True)
        self.state = self.root / 'var/lib/mindflayer-elderbrain'
        self.state.mkdir(parents=True)
        self.compose = self.runtime / 'compose.yaml'
        self.stack = self.units / 'elderbrain-stack.service'
        self.compose.write_text('old compose')
        self.stack.write_text('old unit')
        incoming = self.root / 'incoming'
        incoming.mkdir()
        self.sources = {'compose': incoming / 'compose.yaml', 'stack': incoming / 'stack.service'}
        self.sources['compose'].write_text('offline compose')
        self.sources['stack'].write_text('offline unit')
        self.services = Mock()
        self.services.assert_quiescent = Mock()
        self.maintenance = Maintenance(self.state / 'maintenance', self.services)
        self.enterContext(patch('release_baseline_install.persistent_identity', return_value='fixture'))
        self.migration = Migration(self.maintenance, host_root=self.root)
        self.source_check = self.enterContext(patch.object(self.migration, 'sources', return_value=self.sources))
        self.bootstrap = Mock()

    def install(self):
        return self.migration.install(self.root, self.sources['stack'],
                                      require_bootstrap=self.bootstrap, run=Mock())

    def test_installs_fixed_files_without_recreating_or_stopping_containers(self):
        record = self.install()
        self.assertEqual(record['state'], 'completed')
        self.assertFalse(record['activationReady'])
        self.assertEqual(self.compose.read_text(), 'offline compose')
        self.assertEqual(self.stack.read_text(), 'offline unit')
        self.bootstrap.assert_called_once()
        self.services.snapshot.assert_called_once()
        self.services.validate.assert_called_once()
        self.services.health_check.assert_called_once_with(self.services.snapshot.return_value)
        self.services.run.assert_called_once_with(['systemctl', 'daemon-reload'])
        self.services.stop.assert_not_called()
        self.services.resume_restored.assert_not_called()

    def test_failed_validation_rolls_back_both_files(self):
        self.services.validate.side_effect = ValueError('invalid config')
        with self.assertRaisesRegex(ValueError, 'invalid config'):
            self.install()
        self.assertEqual(self.compose.read_text(), 'old compose')
        self.assertEqual(self.stack.read_text(), 'old unit')
        self.assertEqual(self.maintenance.previous()['state'], 'rolled-back')

    def test_process_loss_after_switch_is_reversed_by_early_recovery(self):
        self.services.validate.side_effect = SystemExit('power loss')
        with self.assertRaises(SystemExit):
            self.install()
        self.assertEqual(self.compose.read_text(), 'offline compose')
        with self.assertRaisesRegex(RuntimeError, 'before starting writers'):
            self.migration.recover(early=False)
        recovered = self.migration.recover(early=True)
        self.assertEqual(recovered['state'], 'rolled-back')
        self.services.assert_quiescent.assert_called_once()
        self.assertEqual(self.compose.read_text(), 'old compose')
        self.assertEqual(self.stack.read_text(), 'old unit')
        self.assertEqual(self.migration.recover(early=False)['state'], 'rolled-back')

    def test_committed_transaction_survives_lost_completion_record(self):
        commit = RestoreTransaction.commit
        def interrupted(transaction):
            commit(transaction)
            raise SystemExit('lost completion record')
        with patch.object(RestoreTransaction, 'commit', interrupted), self.assertRaises(SystemExit):
            self.install()
        self.assertEqual(self.migration.recover(early=True)['state'], 'completed')
        self.assertEqual(self.compose.read_text(), 'offline compose')
        self.assertEqual(self.stack.read_text(), 'offline unit')

    def test_power_loss_between_compose_and_unit_switch_restores_original_pair(self):
        import os
        rename = os.rename
        def interrupted(source, destination):
            if Path(source) == self.stack:
                raise SystemExit('power loss between files')
            return rename(source, destination)
        with patch('restore_transaction.os.rename', side_effect=interrupted), self.assertRaises(SystemExit):
            self.install()
        self.assertEqual(self.compose.read_text(), 'offline compose')
        self.assertEqual(self.stack.read_text(), 'old unit')
        self.assertEqual(self.migration.recover(early=True)['state'], 'rolled-back')
        self.assertEqual(self.compose.read_text(), 'old compose')
        self.assertEqual(self.stack.read_text(), 'old unit')

    def test_missing_recovery_prerequisite_never_starts_transaction(self):
        self.bootstrap.side_effect = ValueError('bootstrap unavailable')
        with self.assertRaisesRegex(ValueError, 'bootstrap unavailable'):
            self.install()
        self.assertFalse(self.maintenance.journal.exists())
        self.assertEqual(self.compose.read_text(), 'old compose')
        self.services.snapshot.assert_not_called()

    def test_early_recovery_refuses_active_writers(self):
        self.services.validate.side_effect = SystemExit('power loss')
        with self.assertRaises(SystemExit):
            self.install()
        self.services.assert_quiescent.side_effect = RuntimeError('writers active')
        with self.assertRaisesRegex(RuntimeError, 'writers active'):
            self.migration.recover(early=True)
        self.assertEqual(self.compose.read_text(), 'offline compose')

    def test_prepared_sources_revalidate_bytes_live_origin_and_cached_images(self):
        fixture = test.test_release_baseline.BaselineTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        prepared = Path(fixture.prepare()['directory'])
        self.compose.write_bytes(fixture.template)
        # Use the real source validator for this test, not the transaction fixture.
        self.migration.sources = Migration.sources.__get__(self.migration)
        result = self.migration.sources(prepared, self.sources['stack'], run=fixture.command)
        self.assertEqual(result['compose'], prepared / 'compose.yaml')
        fixture.images['foundry'] = 'sha256:' + 'f' * 64
        with self.assertRaisesRegex(ValueError, 'unavailable or changed'):
            self.migration.sources(prepared, self.sources['stack'], run=fixture.command)
        (prepared / 'compose.yaml').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'configuration changed'):
            self.migration.sources(prepared, self.sources['stack'], run=fixture.command)


if __name__ == '__main__':
    unittest.main()
