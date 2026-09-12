import fcntl
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'appliance/lib'))
from backup_service import Maintenance, save_record
from host_jobs import JobStore
from release_interlocks import settings_admission, update_admission


class UpdateInterlockTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.state = Path(temporary.name)
        self.jobs = JobStore(self.state / 'jobs')

    def job(self, kind, live=True):
        identity = 'a' * 32
        path = self.jobs.path(identity)
        save_record(path, {'id': identity, 'kind': kind, 'state': 'running', 'createdAt': 1})
        if live:
            descriptor = os.open(path.with_suffix('.lock'), os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            self.addCleanup(os.close, descriptor)
        return identity

    def test_live_flashing_job_excludes_update(self):
        self.job('keypad-install')
        with self.assertRaisesRegex(RuntimeError, 'host job'), update_admission(self.state):
            self.fail('Update admitted during flashing')

    def test_stale_job_does_not_prove_running_worker(self):
        identity = self.job('backup', live=False)
        with update_admission(self.state):
            self.assertEqual(self.jobs.read(identity)['state'], 'interrupted')

    def test_only_live_update_owner_can_exempt_itself(self):
        identity = self.job('keypad-install')
        with self.assertRaises(ValueError), update_admission(self.state, owner=identity):
            pass
        record = self.jobs.read(identity)
        record['kind'] = 'update'
        save_record(self.jobs.path(identity), record)
        with update_admission(self.state, owner=identity):
            with self.assertRaisesRegex(RuntimeError, 'admission'), update_admission(self.state, owner=identity):
                pass

    def test_settings_rejected_during_live_or_interrupted_maintenance(self):
        maintenance = Maintenance(self.state / 'maintenance', None)
        with maintenance.locked():
            with self.assertRaises(RuntimeError), settings_admission(self.state):
                pass
        save_record(maintenance.journal, {'operation': 'update', 'state': 'recovery-required'})
        with self.assertRaisesRegex(RuntimeError, 'Recover maintenance'), settings_admission(self.state):
            pass
        save_record(maintenance.journal, {'operation': 'update', 'state': 'completed'})
        with settings_admission(self.state):
            pass


if __name__ == '__main__':
    unittest.main()
