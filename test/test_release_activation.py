from contextlib import contextmanager
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import test.test_release_prepare as preparation_fixture
from backup_service import Maintenance
from release_activation import Activation


class Services:
    def __init__(self, root):
        self.root = root
        self.events = []
        self.fail_new = False
        self.fail_stop = False

    def snapshot(self):
        return {'fixture': True}

    def stop(self, saved):
        self.events.append('stop')
        if self.fail_stop:
            raise RuntimeError('writers still running')

    def validate(self):
        self.events.append('validate')

    def resume_restored(self, saved):
        self.events.append('start')
        if (self.root / 'runtime/VERSION').read_text() == 'new':
            (self.root / 'data').write_text('new runtime changed data')
            if self.fail_new:
                raise RuntimeError('new runtime unhealthy')


class ActivationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        preparation_fixture.ReleasePrepareTests.setUpClass()
        cls.addClassCleanup(preparation_fixture.ReleasePrepareTests.doClassCleanups)

    def setUp(self):
        self.fixture = preparation_fixture.ReleasePrepareTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.signed_dependencies()
        self.root = self.fixture.root
        runtime = self.root / 'runtime'
        staged = self.root / 'incoming'
        runtime.mkdir()
        staged.mkdir()
        (runtime / 'VERSION').write_text('old')
        (staged / 'VERSION').write_text('new')
        (self.root / 'data').write_text('original')
        self.sources = {'runtime': staged}
        self.services = Services(self.root)
        self.maintenance = Maintenance(self.root / 'maintenance', self.services)
        self.released = []
        self.restored = []
        self.lock_held = False

        @contextmanager
        def exclusive():
            self.lock_held = True
            try:
                yield
            finally:
                self.lock_held = False

        def checkpoint(record):
            self.assertTrue(self.lock_held)
            self.assertEqual(self.services.events[-1], 'stop')
            (self.root / 'checkpoint').write_text((self.root / 'data').read_text())
            record['rollbackCheckpoint'] = 'fixture-checkpoint'

        def restore_checkpoint(record):
            self.assertTrue(self.lock_held)
            self.assertEqual(self.services.events[-1], 'stop')
            (self.root / 'data').write_text((self.root / 'checkpoint').read_text())
            self.restored.append(record['id'])

        self.activation = Activation(self.maintenance, {'runtime': runtime}, checkpoint=checkpoint,
            restore_checkpoint=restore_checkpoint, release_checkpoint=lambda record: self.released.append(record['id']),
            refresh=lambda: None, exclusive=exclusive)

    def activate(self):
        bundle = self.fixture.bundle
        return self.activation.activate((bundle / 'manifest.json').read_bytes(),
            (bundle / 'manifest.sig').read_bytes(), self.fixture.public, lambda release: self.sources)

    def test_healthy_update_retains_previous_runtime(self):
        result = self.activate()
        self.assertEqual(result['state'], 'completed')
        self.assertEqual((self.root / 'runtime/VERSION').read_text(), 'new')
        transaction = self.activation.transaction(result)
        previous = transaction.location(transaction.read(), 'runtime') / 'previous/VERSION'
        self.assertEqual(previous.read_text(), 'old')
        self.assertEqual(self.restored, [])
        self.assertEqual(self.released, [result['id']])

    def test_failed_health_restores_code_and_changed_data(self):
        self.services.fail_new = True
        with self.assertRaisesRegex(RuntimeError, 'unhealthy'):
            self.activate()
        self.assertEqual((self.root / 'runtime/VERSION').read_text(), 'old')
        self.assertEqual((self.root / 'data').read_text(), 'original')
        self.assertEqual(self.maintenance.previous()['state'], 'rolled-back')
        self.assertEqual(len(self.restored), 1)
        self.activation.recover()
        self.assertEqual(len(self.restored), 1)

    def test_checkpoint_failure_never_switches_runtime(self):
        self.activation.checkpoint = lambda record: None
        with self.assertRaisesRegex(ValueError, 'checkpoint'):
            self.activate()
        self.assertEqual((self.root / 'runtime/VERSION').read_text(), 'old')
        self.assertEqual(self.restored, [])

    def test_crash_mid_switch_recovers_old_runtime(self):
        rename = os.rename
        def crash(source, destination):
            rename(source, destination)
            if Path(source) == self.root / 'runtime':
                raise SystemExit('power loss')
        with patch('restore_transaction.os.rename', side_effect=crash):
            with self.assertRaises(SystemExit):
                self.activate()
        self.assertFalse((self.root / 'runtime').exists())
        result = self.activation.recover()
        self.assertEqual(result['state'], 'rolled-back')
        self.assertEqual((self.root / 'runtime/VERSION').read_text(), 'old')

    def test_crash_during_health_restores_checkpoint_before_old_start(self):
        def crash(saved):
            (self.root / 'data').write_text('partial migration')
            raise SystemExit('power loss')
        with patch.object(self.services, 'resume_restored', side_effect=crash):
            with self.assertRaises(SystemExit):
                self.activate()
        self.activation.recover()
        self.assertEqual((self.root / 'runtime/VERSION').read_text(), 'old')
        self.assertEqual((self.root / 'data').read_text(), 'original')

    def test_crash_after_commit_keeps_healthy_new_runtime(self):
        write = self.activation.write
        def crash(record, state):
            if state == 'completed':
                raise SystemExit('power loss after commit')
            write(record, state)
        with patch.object(self.activation, 'write', side_effect=crash):
            with self.assertRaises(SystemExit):
                self.activate()
        result = self.activation.recover()
        self.assertEqual(result['state'], 'completed')
        self.assertEqual((self.root / 'runtime/VERSION').read_text(), 'new')
        self.assertEqual(self.restored, [])

    def test_stop_failure_blocks_recovery_without_mutating_runtime(self):
        self.services.fail_stop = True
        with self.assertRaisesRegex(RuntimeError, 'writers still running'):
            self.activate()
        self.assertEqual(self.maintenance.previous()['state'], 'recovery-required')
        self.assertEqual((self.root / 'runtime/VERSION').read_text(), 'old')
        with self.assertRaisesRegex(RuntimeError, 'Update recovery'):
            self.maintenance.recover()
        self.services.fail_stop = False
        self.assertEqual(self.activation.recover()['state'], 'rolled-back')

    def test_signature_failure_never_stops_services(self):
        bundle = self.fixture.bundle
        with self.assertRaises(ValueError):
            self.activation.activate((bundle / 'manifest.json').read_bytes() + b' ',
                (bundle / 'manifest.sig').read_bytes(), self.fixture.public, lambda release: self.sources)
        self.assertEqual(self.services.events, [])

    def test_checkpoint_restore_failure_keeps_services_stopped_until_recovery(self):
        self.services.fail_new = True
        with patch.object(self.activation, 'restore_checkpoint', side_effect=RuntimeError('checkpoint unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'checkpoint unavailable'):
                self.activate()
        self.assertEqual(self.services.events[-1], 'stop')
        self.assertEqual(self.maintenance.previous()['state'], 'recovery-required')
        self.assertEqual(self.released, [])
        self.activation.recover()
        self.assertEqual((self.root / 'data').read_text(), 'original')
        self.assertEqual(self.maintenance.previous()['state'], 'rolled-back')

    def test_settings_lock_released_before_new_and_old_service_start(self):
        resume = self.services.resume_restored
        def checked(saved):
            self.assertFalse(self.lock_held)
            resume(saved)
        self.services.fail_new = True
        with patch.object(self.services, 'resume_restored', side_effect=checked):
            with self.assertRaisesRegex(RuntimeError, 'unhealthy'):
                self.activate()
        self.assertFalse(self.lock_held)


if __name__ == '__main__':
    unittest.main()
