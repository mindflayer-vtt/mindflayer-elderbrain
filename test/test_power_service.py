import fcntl
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import test.test_host_jobs
from backup_service import save_record
from host_jobs import JobStore
from power_service import operate, pending


class PowerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.state = self.root / 'var/lib/mindflayer-elderbrain'
        self.state.mkdir(parents=True)
        self.storage = self.enterContext(patch('restore_service.persistent_identity', return_value='verified'))
        self.run = Mock()

    def power(self, action='reboot'):
        return operate(action, host_root=self.root, run=self.run)

    def test_requested_power_prevents_later_jobs_until_next_boot(self):
        result = self.power()
        self.assertEqual(result['state'], 'requested')
        self.assertTrue(pending(self.state))
        self.assertEqual(self.run.call_args.args[0], ['systemctl', '--no-block', 'reboot'])
        with self.assertRaisesRegex(RuntimeError, 'power operation'):
            JobStore(self.state / 'jobs').submit('backup')
        save_record(self.state / 'power.json', {**result, 'bootId': 'previous-boot'})
        self.assertFalse(pending(self.state))

    def test_active_worker_prevents_power(self):
        jobs = JobStore(self.state / 'jobs')
        path = jobs.path('a' * 32)
        save_record(path, {'id': 'a' * 32, 'kind': 'keypad-install', 'state': 'running', 'createdAt': 1})
        fd = os.open(path.with_suffix('.lock'), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            with self.assertRaisesRegex(RuntimeError, 'host job'):
                self.power('shutdown')
            self.run.assert_not_called()
        finally:
            os.close(fd)

    def test_unfinished_maintenance_and_missing_storage_prevent_power(self):
        (self.state / 'maintenance').mkdir()
        save_record(self.state / 'maintenance/maintenance.json', {'state': 'verifying-update'})
        with self.assertRaisesRegex(RuntimeError, 'maintenance'):
            self.power()
        self.storage.return_value = None
        with self.assertRaisesRegex(ValueError, 'persistent storage'):
            self.power()
        self.run.assert_not_called()

    def test_rejected_systemd_request_does_not_leave_pending_power(self):
        self.run.side_effect = RuntimeError('rejected')
        with self.assertRaisesRegex(RuntimeError, 'rejected'):
            self.power('shutdown')
        self.assertFalse(pending(self.state))
        self.assertEqual(json.loads((self.state / 'power.json').read_text())['state'], 'failed')

    def test_pending_settings_prevent_power_and_accepted_power_prevents_settings(self):
        from release_interlocks import settings_admission
        directory = self.state / 'network-transaction'
        directory.mkdir()
        save_record(directory / 'state.json', {'phase': 'pending'})
        with self.assertRaisesRegex(RuntimeError, 'pending settings'):
            self.power()
        self.run.assert_not_called()
        save_record(directory / 'state.json', {'phase': 'confirmed'})
        self.power()
        with self.assertRaisesRegex(RuntimeError, 'power operation'):
            with settings_admission(self.state):
                self.fail('Power-pending settings admission must not succeed')


if __name__ == '__main__':
    unittest.main()
