import fcntl
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'appliance/lib'))
from snapshot_service import stable_settings, retention_settings
from backup_service import Maintenance


class SnapshotCoordinationTests(unittest.TestCase):
    def test_retention_change_excluded_by_active_or_interrupted_maintenance(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            maintenance = Maintenance(state / 'maintenance', None)
            snapshots = Mock()
            with patch('snapshot_service.store', return_value=snapshots):
                with maintenance.locked():
                    with self.assertRaises(RuntimeError):
                        retention_settings({'enabled': True, 'keep': 3}, state=state)
                maintenance.journal.write_text('{"state":"recovery-required"}')
                with self.assertRaises(RuntimeError):
                    retention_settings({'enabled': True, 'keep': 3}, state=state)
                snapshots.retention.assert_not_called()
                maintenance.journal.write_text('{"state":"completed"}')
                retention_settings({'enabled': True, 'keep': 3}, state=state)
                snapshots.retention.assert_called_once_with({'enabled': True, 'keep': 3})

    def test_pending_settings_rejected_and_locks_released(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            for name in ('display-preview', 'network-transaction'):
                (state / name).mkdir()
                record = state / name / 'state.json'
                record.write_text(json.dumps({'phase': 'pending'}))
                with self.assertRaises(RuntimeError):
                    with stable_settings(state):
                        self.fail('Pending change accepted')
                record.write_text(json.dumps({'phase': 'confirmed'}))
            with stable_settings(state):
                with self.assertRaises(RuntimeError):
                    with stable_settings(state):
                        self.fail('Concurrent settings lock accepted')

    def test_durable_pause_and_locks_release_before_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            events = []
            class Services:
                def snapshot(self):
                    return {'fixture': True}
                def stop(self, saved):
                    events.append('stop')
                    with self_test.assertRaises(RuntimeError):
                        with stable_settings(state):
                            pass
                def resume(self, saved):
                    with stable_settings(state):
                        events.append('resume')
            self_test = self
            maintenance = Maintenance(state / 'maintenance', Services())
            with maintenance.window('snapshot', exclusive=lambda: stable_settings(state)):
                self.assertEqual(maintenance.previous()['state'], 'working')
                events.append('capture')
            self.assertEqual(events, ['stop', 'capture', 'resume'])
            self.assertEqual(maintenance.previous()['state'], 'completed')
