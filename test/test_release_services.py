import json
import sys
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'appliance/lib'))
from backup_service import HostServices
from release_services import UpdateServices


class UpdateServiceTests(unittest.TestCase):
    def test_local_baseline_ids_are_immutable_but_tags_still_fail(self):
        for service in self.config['services'].values():
            service['image'] = 'sha256:' + 'b' * 64
        self.services.validate()
        self.config['services']['foundry']['image'] = 'foundry:latest'
        with self.assertRaisesRegex(ValueError, 'offline digest-pinned'):
            self.services.validate()

    def setUp(self):
        self.calls = []
        self.health = []
        self.services = UpdateServices(Path('/opt/fixture'), health_check=lambda saved: self.health.append(saved))
        self.services.run = self.execute
        self.saved = {'compose': ['elderbrain-setup'], 'project': 'elderbrain', 'graphics': True,
                      'hostUnits': ['elderbrain-management.service']}
        self.config = {'services': {name: {'image': 'example.test/image@sha256:' + 'a' * 64,
                                         'pull_policy': 'never'} for name in HostServices.ALLOWED}}
        self.stack = 'ActiveState=active\nSubState=exited\n'
        self.unit_state = 'active'

    def execute(self, args, *, check=True):
        self.calls.append(args)
        output = ''
        if args[:2] == ['systemctl', 'show']:
            output = self.stack
        elif args[:2] == ['systemctl', 'is-active']:
            output = self.unit_state
        elif args[-3:] == ['config', '--format', 'json']:
            output = json.dumps(self.config)
        elif args[:2] == ['docker', 'ps'] or 'ps' in args:
            output = 'container-id'
        elif args[:2] == ['docker', 'inspect']:
            output = json.dumps({'Running': True, 'Health': {'Status': 'healthy'}})
        return SimpleNamespace(stdout=output, returncode=0)

    def test_snapshot_records_allowlisted_workers_only_after_stable_stack(self):
        with patch.object(HostServices, 'snapshot', return_value=dict(self.saved)):
            saved = self.services.snapshot()
        self.assertEqual(saved['hostUnits'], list(UpdateServices.UNITS))
        self.stack = 'ActiveState=activating\nSubState=start\n'
        with self.assertRaisesRegex(RuntimeError, 'stable'):
            self.services.snapshot()

    def test_transitional_or_missing_worker_rejected(self):
        self.unit_state = 'unknown'
        with patch.object(HostServices, 'snapshot', return_value=dict(self.saved)):
            with self.assertRaisesRegex(RuntimeError, 'worker'):
                self.services.snapshot()

    def test_stop_does_not_parse_changed_compose_or_invoke_stack_unit(self):
        self.services.stop(self.saved)
        self.assertEqual(self.calls[0], ['systemctl', 'stop', *UpdateServices.UNITS])
        self.assertIn(['docker', 'stop', '--time', '60', 'container-id'], self.calls)
        self.assertFalse(any('compose' in args for args in self.calls))
        self.assertFalse(any('elderbrain-stack.service' in args for args in self.calls))

    def test_restarts_are_offline_and_health_precedes_graphics(self):
        def health(saved):
            self.assertFalse(any(args == ['systemctl', 'start', 'elderbrain-graphics.service'] for args in self.calls))
            self.health.append(saved)
        self.services.health_check = health
        self.services.resume_restored(self.saved)
        start = next(args for args in self.calls if 'up' in args)
        self.assertIn('--no-build', start)
        self.assertEqual(start[start.index('--pull') + 1], 'never')
        self.assertIn('--no-deps', start)
        self.assertEqual(start[-1], 'elderbrain-setup')
        self.assertEqual(self.health, [self.saved])
        self.assertIn(['systemctl', 'start', 'elderbrain-management.service'], self.calls)
        self.assertNotIn(['systemctl', 'start', 'elderbrain-network-watchdog.service'], self.calls)
        self.assertFalse(any('elderbrain-stack.service' in args for args in self.calls))

    def test_failed_api_health_does_not_start_graphics(self):
        def unhealthy(saved):
            raise RuntimeError('API health failed')
        self.services.health_check = unhealthy
        with self.assertRaisesRegex(RuntimeError, 'API health'):
            self.services.resume_restored(self.saved)
        self.assertNotIn(['systemctl', 'start', 'elderbrain-graphics.service'], self.calls)

    def test_validate_rejects_build_pull_and_mutable_images(self):
        self.services.validate()
        service = self.config['services']['elderbrain-setup']
        for key, value in [('build', '.'), ('pull_policy', 'always'), ('image', 'example.test/image:latest')]:
            old = dict(service)
            service[key] = value
            with self.assertRaisesRegex(ValueError, 'offline'):
                self.services.validate()
            service.clear()
            service.update(old)
        self.config['services'].pop('foundry')
        with self.assertRaisesRegex(ValueError, 'exact coordinated'):
            self.services.validate()

    def test_saved_unit_injection_rejected_before_commands(self):
        self.saved['hostUnits'] = ['ssh.service']
        with self.assertRaises(ValueError):
            self.services.stop(self.saved)
        with self.assertRaises(ValueError):
            self.services.resume_restored(self.saved)
        self.assertEqual(self.calls, [])

    def test_early_recovery_checks_units_without_starting_docker(self):
        calls = []
        def inactive(args, **options):
            calls.append(args)
            return SimpleNamespace(stdout='inactive\n', returncode=3)
        self.services.run = inactive
        self.services.assert_quiescent()
        self.assertIn(['systemctl', 'is-active', 'containerd.service'], calls)
        self.assertIn(['systemctl', 'is-active', 'elderbrain-network-recovery.service'], calls)
        self.assertTrue(all(args[:2] == ['systemctl', 'is-active'] for args in calls))
        self.services.run = lambda *args, **options: SimpleNamespace(stdout='active\n', returncode=0)
        with self.assertRaisesRegex(RuntimeError, 'inactive'):
            self.services.assert_quiescent()
        self.services.run = lambda *args, **options: SimpleNamespace(stdout='unknown\n', returncode=4)
        with self.assertRaisesRegex(RuntimeError, 'inactive'):
            self.services.assert_quiescent()


if __name__ == '__main__':
    unittest.main()
