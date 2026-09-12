import importlib.util
import json
from pathlib import Path
import tempfile
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'appliance/lib'))
spec = importlib.util.spec_from_file_location('display_preview', ROOT / 'appliance/lib/display_preview.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DisplayPreviewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.clock = 1000
        self.monotonic = 100
        self.calls = []
        self.store = module.DisplayPreview(self.directory.name, clock=lambda: self.clock,
            monotonic=lambda: self.monotonic, reboot_id='boot-one', apply=lambda: self.calls.append('restart'))
        self.store.config.parent.mkdir()
        self.old = {'configured': False, 'views': [{'output': '', 'url': 'https://old.example', 'mode': 'admin'}]}
        self.new = {'configured': True, 'views': [{'output': '', 'url': 'https://new.example', 'mode': 'player'}]}
        self.store.config.write_text(json.dumps(self.old))

    def test_preview_does_not_commit_until_confirmed(self):
        preview = self.store.begin(self.new)
        self.assertEqual(self.store.effective(), self.new)
        self.assertEqual(json.loads(self.store.current()), self.old)
        self.assertNotIn('candidate', preview)
        self.assertEqual(self.store.confirm(preview['id'])['phase'], 'confirmed')
        self.assertEqual(json.loads(self.store.current()), self.new)
        self.assertEqual(self.store.config.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('candidate', self.store.read())

    def test_expiry_survives_service_restart_and_rejects_late_confirmation(self):
        preview = self.store.begin(self.new, 15)
        self.clock += 16
        self.assertEqual(self.store.effective(), self.old)
        other = module.DisplayPreview(self.directory.name, clock=lambda: self.clock,
            monotonic=lambda: self.monotonic, reboot_id='boot-one', apply=lambda: self.calls.append('restart'))
        self.assertEqual(other.recover()['phase'], 'rolled-back')
        with self.assertRaises(ValueError):
            other.confirm(preview['id'])
        self.assertEqual(json.loads(self.store.current()), self.old)

    def test_backward_clock_and_reboot_cannot_extend_preview(self):
        self.store.begin(self.new, 15)
        self.clock -= 1000
        self.monotonic += 16
        self.assertEqual(self.store.recover()['phase'], 'rolled-back')
        self.store.begin(self.new)
        self.store.boot = 'boot-two'
        self.assertEqual(self.store.effective(), self.old)
        self.assertEqual(self.store.recover()['phase'], 'rolled-back')

    def test_conflicts_and_concurrent_writes_are_not_overwritten(self):
        preview = self.store.begin(self.new)
        with self.assertRaises(ValueError):
            self.store.begin(self.new)
        with self.assertRaises(ValueError):
            self.store.confirm('wrong')
        changed = {**self.old, 'domain': 'changed.example'}
        self.store.config.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, 'changed during'):
            self.store.confirm(preview['id'])
        self.assertEqual(json.loads(self.store.current()), changed)

    def test_failed_restart_retains_retryable_rollback(self):
        def fail():
            raise RuntimeError('restart unavailable')
        self.store.apply = fail
        with self.assertRaises(RuntimeError):
            self.store.begin(self.new)
        self.assertEqual(self.store.read()['phase'], 'rolling-back')
        self.assertEqual(self.store.effective(), self.old)
        self.store.apply = lambda: None
        self.assertEqual(self.store.recover()['phase'], 'rolled-back')

    def test_interrupted_confirm_recovers_correct_committed_state(self):
        self.store.begin(self.new)
        record = self.store.read()
        record['phase'] = 'committing'
        self.store.write(record)
        self.store.commit(self.new)
        self.assertEqual(self.store.recover()['phase'], 'confirmed')
        self.assertEqual(json.loads(self.store.current()), self.new)

    def test_cancel_and_validation(self):
        preview = self.store.begin(self.new)
        self.assertEqual(self.store.cancel(preview['id'])['phase'], 'rolled-back')
        for value in ({}, {'configured': True, 'views': []}, {'configured': True, 'views': [{'url': 'file:///etc/passwd'}]}):
            with self.assertRaises(ValueError):
                self.store.begin(value)
