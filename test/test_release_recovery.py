from contextlib import ExitStack
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'appliance/lib'))
from release_recovery import health, recover


class RecoveryEntryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.socket_factory = self.stack.enter_context(patch('release_recovery.socket.socket'))
        self.socket = self.socket_factory.return_value.__enter__.return_value
        self.socket.getsockopt.return_value = struct.pack('3i', 123, 0, 0)
        self.socket.makefile.return_value.__enter__.side_effect = lambda: io.BytesIO(
            (json.dumps({'ok': True, 'output': json.dumps({'history': []})}) + '\n').encode())
        self.tls = self.stack.enter_context(patch('release_recovery.ssl.create_default_context'))
        self.https = self.stack.enter_context(patch('release_recovery.http.client.HTTPSConnection'))
        self.response = self.https.return_value.getresponse.return_value
        self.response.status = 200
        self.response.read.return_value = b'{"ok":true}'
        self.saved = {'hostUnits': ['elderbrain-management.service'], 'compose': ['elderbrain-setup']}

    def test_bridge_and_proxy_health_are_read_only_bounded_and_ca_verified(self):
        health(self.saved, Path('/fixture/state'))
        self.socket.sendall.assert_called_once_with(b'host-metrics\n')
        self.socket.settimeout.assert_called_once_with(10)
        self.tls.assert_called_once_with(cafile='/fixture/state/traefik/tls/ca.crt')
        self.https.assert_called_once_with('127.0.0.1', timeout=10, context=self.tls.return_value)
        self.https.return_value.request.assert_called_once_with('GET', '/elderbrain/health', headers={'Accept': 'application/json'})
        self.response.read.assert_called_once_with(4097)
        self.https.return_value.close.assert_called_once()

    def test_untrusted_management_peer_prevents_proxy_check(self):
        self.socket.getsockopt.return_value = struct.pack('3i', 123, 1000, 1000)
        with self.assertRaisesRegex(ValueError, 'not root'):
            health(self.saved, Path('/fixture/state'))
        self.https.assert_not_called()

    def test_redirect_oversize_and_nonboolean_health_are_rejected(self):
        for status, body in [(302, b'{}'), (200, b'x' * 4097), (200, b'{"ok":1}')]:
            self.response.status, self.response.read.return_value = status, body
            with self.assertRaisesRegex(ValueError, 'proxy health'):
                health({'hostUnits': [], 'compose': ['elderbrain-setup']}, Path('/fixture/state'))

    def test_inactive_components_are_not_probed(self):
        health({'hostUnits': [], 'compose': []}, Path('/fixture/state'))
        self.socket_factory.assert_not_called()
        self.https.assert_not_called()

    def test_recovery_wires_fixed_targets_and_redacts_internal_record(self):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as patches:
            root = Path(temporary)
            patches.enter_context(patch('release_recovery.persistent_identity', return_value={'data_uuid': 'fixture'}))
            maintenance = patches.enter_context(patch('release_recovery.Maintenance')).return_value
            maintenance.previous.return_value = {'operation': 'update'}
            checkpoints = patches.enter_context(patch('release_recovery.UpdateCheckpoints')).return_value
            activation = patches.enter_context(patch('release_recovery.Activation'))
            activation.return_value.recover_files.return_value = {'id': 'a' * 32, 'state': 'files-recovered',
                                                                  'version': '1.2.3', 'services': {'private': 'state'}}
            result = recover('files', host_root=root)
            self.assertEqual(set(result), {'id', 'state', 'version'})
            activation.return_value.recover_files.assert_called_once()
            activation.return_value.recover.assert_not_called()
            options = activation.call_args.kwargs
            self.assertIs(options['restore_checkpoint'], checkpoints.restore)
            targets = activation.call_args.args[1]
            self.assertEqual(targets['opt/mindflayer-elderbrain'], root / 'opt/mindflayer-elderbrain')

    def test_missing_storage_prevents_maintenance_creation(self):
        with patch('release_recovery.persistent_identity', return_value=None), patch('release_recovery.Maintenance') as maintenance:
            with self.assertRaisesRegex(ValueError, 'persistent storage'):
                recover('files')
            maintenance.assert_not_called()

    def test_only_final_recovery_reconciles_matching_maintenance_job(self):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as patches:
            root = Path(temporary)
            patches.enter_context(patch('release_recovery.persistent_identity', return_value='fixture'))
            maintenance = patches.enter_context(patch('release_recovery.Maintenance')).return_value
            outcome = {'operation': 'update', 'id': 'a' * 32, 'jobId': 'b' * 32, 'state': 'rolled-back'}
            maintenance.previous.return_value = outcome
            patches.enter_context(patch('release_recovery.UpdateCheckpoints'))
            activation = patches.enter_context(patch('release_recovery.Activation')).return_value
            activation.recover.return_value = outcome
            activation.recover_files.return_value = outcome
            jobs = patches.enter_context(patch('host_jobs.JobStore')).return_value
            recover('files', host_root=root)
            jobs.reconcile_update.assert_not_called()
            recover('finish', host_root=root)
            jobs.reconcile_update.assert_called_once_with(outcome)
            jobs.reconcile_update.reset_mock()
            maintenance.previous.return_value = {**outcome, 'id': 'c' * 32}
            recover('finish', host_root=root)
            jobs.reconcile_update.assert_not_called()

    def test_baseline_recovery_routes_to_fixed_migration_before_update_adapter(self):
        with patch('release_recovery.persistent_identity', return_value='fixture'), \
                patch('release_recovery.Maintenance') as maintenance, \
                patch('release_recovery.Migration') as migration, \
                patch('release_recovery.UpdateCheckpoints') as checkpoints:
            maintenance.return_value.previous.return_value = {'operation': 'baseline'}
            migration.return_value.recover.return_value = {'id': 'a' * 32, 'state': 'rolled-back', 'private': 'omit'}
            self.assertEqual(recover('files'), {'id': 'a' * 32, 'state': 'rolled-back'})
            migration.return_value.recover.assert_called_once_with(early=True)
            checkpoints.assert_not_called()


if __name__ == '__main__':
    unittest.main()
