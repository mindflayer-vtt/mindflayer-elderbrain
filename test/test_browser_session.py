import importlib.util
from pathlib import Path
import unittest
import sys
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('browser_session', ROOT / 'provisioning/graphics/browser-session.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BrowserSessionTests(unittest.TestCase):
    def test_worker_output_is_bounded_and_only_exposes_allowed_states(self):
        reader, writer = os.pipe()
        try:
            os.set_blocking(reader, False)
            with os.fdopen(reader, 'rb', closefd=False) as stream:
                child = SimpleNamespace(stdout=stream)
                os.write(writer, b'{"state":"rea')
                self.assertIsNone(module.drain_status(child, None, 'current'))
                os.write(writer, b'dy","password":"must-not-escape"}\n')
                value = module.drain_status(child, None, 'current')
                self.assertEqual(value['state'], 'ready')
                self.assertEqual(set(value), {'state', 'revision', 'observedAt'})
                os.write(writer, b'{"state":"private-invalid-value"}\n')
                self.assertEqual(module.drain_status(child, value, 'current'), value)
                os.write(writer, b'x' * 5000)
                self.assertEqual(module.drain_status(child, value, 'current')['state'], 'unavailable')
        finally:
            os.close(reader)
            os.close(writer)

    def test_per_view_service_uses_cgroup_cleanup_and_safe_description(self):
        spec = importlib.util.spec_from_file_location('browser_process', ROOT / 'provisioning/graphics/browser_process.py')
        process = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(process)
        command = process.service_command(1, ['chrome', 'https://local/#private-capability'], {'XDG_RUNTIME_DIR': '/run/elderbrain-kiosk'})
        self.assertIn('--property=KillMode=control-group', command)
        self.assertIn('--description=Elderbrain browser view 1', command)
        self.assertIn('--setenv=XDG_RUNTIME_DIR=/run/elderbrain-kiosk', command)
        self.assertEqual(command[-2:], ['chrome', 'https://local/#private-capability'])
        self.assertTrue(process.manager_environment()['XDG_RUNTIME_DIR'].startswith('/run/user/'))

    def test_beamer_packet_has_fixed_destination_and_separate_profile(self):
        secret = {'revision': 'a' * 32, 'password': 'test-private-password'}
        packet = module.worker_packet('/usr/bin/google-chrome-stable', {'index': 1, 'mode': 'player', 'urls': ['https://untrusted.example']}, secret)
        self.assertEqual(packet['origin'], 'http://127.0.0.1:30000')
        self.assertTrue(packet['profile'].endswith('profile-1-player'))
        self.assertEqual(packet['credential'], secret)
        with self.assertRaises(ValueError):
            module.worker_packet('chrome', {'index': 0, 'mode': 'admin'}, secret)

    def test_one_screen_does_not_launch_two_overlapping_browsers(self):
        views = [{'output': '', 'mode': mode, 'url': 'https://foundry.example'} for mode in ('admin', 'player')]
        result = module.plan({'configured': True, 'views': views}, [{'name': 'DP-1', 'active': True}], 'test-token')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['mode'], 'admin')
        self.assertEqual(result[0]['urls'], [module.SETUP + '#kiosk-keyboard=test-token', 'https://foundry.example'])

    def test_saved_urls_apply_before_onboarding_is_complete(self):
        views = [{'output': '', 'mode': 'admin', 'url': 'http://foundry.home.viromania.com/',
                  'tabs': ['https://open.spotify.com/']}]
        result = module.plan({'configured': False, 'views': views}, [{'name': 'DP-1', 'active': True}], 'token')
        self.assertEqual(result[0]['urls'], [module.SETUP + '#kiosk-keyboard=token',
                         'http://foundry.home.viromania.com/', 'https://open.spotify.com/'])

    def test_explicit_disconnected_and_hotplug_assignments(self):
        views = [{'output': '', 'url': 'https://foundry.example'}, {'output': 'DP-1', 'url': 'https://foundry.example'}]
        config = {'configured': True, 'views': views}
        outputs = [{'name': name, 'active': True} for name in ('DP-1', 'HDMI-A-1')]
        plan = module.plan(config, outputs, 'token')
        self.assertEqual([view['output'] for view in plan], ['HDMI-A-1', 'DP-1'])
        self.assertEqual(module.plan(config, outputs[:1], 'token')[0]['index'], 1)
        views[0]['output'] = 'absent'
        self.assertEqual(len(module.plan(config, outputs, 'token')), 1)
        self.assertEqual(module.plan(config, [], 'token'), [])

    def test_virtual_terminal_output_suspension_keeps_existing_views(self):
        self.assertTrue(module.outputs_suspended([], {0: object()}))
        self.assertFalse(module.outputs_suspended([], {}))
        self.assertFalse(module.outputs_suspended(
            [{'name': 'DP-1', 'active': True}], {0: object()}))

    def test_modes_and_profile_isolation(self):
        views = [{'mode': mode, 'url': 'https://foundry.example', 'tabs': ['https://notes.example']} for mode in ('admin', 'player')]
        plan = module.plan({'configured': True, 'views': views}, [{'name': name, 'active': True} for name in ('DP-1', 'DP-2')], 'token')
        admin = module.browser_args('chrome', plan[0])
        player = module.browser_args('chrome', plan[1])
        self.assertNotIn('--kiosk', admin)
        self.assertIn('--kiosk', player)
        for args in (admin, player):
            self.assertIn('--hide-crash-restore-bubble', args)
            self.assertNotIn('--disable-session-crashed-bubble', args)
        worker = (ROOT / 'provisioning/graphics/beamer-worker.mjs').read_text()
        self.assertIn("'--hide-crash-restore-bubble'", worker)
        self.assertNotIn('--disable-session-crashed-bubble', worker)
        self.assertEqual(plan[0]['urls'][-1], 'https://notes.example')
        self.assertEqual(len(plan[1]['urls']), 1)
        self.assertNotEqual(next(arg for arg in admin if arg.startswith('--user-data-dir')), next(arg for arg in player if arg.startswith('--user-data-dir')))

    def test_first_boot_uses_one_admin_browser_and_unsafe_urls_fail(self):
        result = module.plan({'configured': False}, [{'name': 'DP-1', 'active': True}, {'name': 'DP-2', 'active': True}], 'token')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['mode'], 'admin')
        for value in ('file:///etc/passwd', 'https://user:password@example.com', 'https://example.com\n--bad'):
            with self.assertRaises(ValueError):
                module.safe_url(value)

    def test_launcher_wiring(self):
        self.assertIn('ExecStart=/usr/bin/sway --config /run/elderbrain-browser/sway.conf', (ROOT / 'provisioning/systemd/elderbrain-graphics.service').read_text())
        self.assertIn("project_sway('/opt/mindflayer-elderbrain/sway.conf', directory, group)", (ROOT / 'provisioning/graphics/prepare-browser.py').read_text())
        self.assertIn('exec python3 /opt/mindflayer-elderbrain/browser-session.py', (ROOT / 'provisioning/graphics/browser-launcher').read_text())
        self.assertIn('"$RUNTIME/browser-session.py"', (ROOT / 'provisioning/install.sh').read_text())
        self.assertNotIn('fullscreen enable', (ROOT / 'provisioning/graphics/sway.conf').read_text())
        self.assertIn('ExecStartPre=+/usr/bin/python3 /opt/mindflayer-elderbrain/prepare-browser.py', (ROOT / 'provisioning/systemd/elderbrain-graphics.service').read_text())

    def test_projection_excludes_non_display_admin_data(self):
        spec = importlib.util.spec_from_file_location('prepare_browser', ROOT / 'provisioning/graphics/prepare-browser.py')
        projection = importlib.util.module_from_spec(spec)
        with patch.object(sys, 'path', [str(ROOT / 'appliance/lib'), *sys.path]):
            spec.loader.exec_module(projection)
        with tempfile.TemporaryDirectory() as temporary, patch.object(projection.os, 'fchown'):
            root = Path(temporary)
            private = root / 'private'
            private.mkdir(mode=0o700)
            (private / 'sway.conf').write_text('input * xkb_layout us\n')
            (private / 'appliance.env').write_text('PRIVATE=not-for-kiosk\n')
            target = root / 'public'
            target.mkdir()
            projection.project_sway(private / 'sway.conf', target, 999)
            self.assertEqual((target / 'sway.conf').read_text(), 'input * xkb_layout us\n')
            self.assertEqual((target / 'sway.conf').stat().st_mode & 0o777, 0o640)
            self.assertEqual([p.name for p in target.iterdir()], ['sway.conf'])
            self.assertEqual(private.stat().st_mode & 0o777, 0o700)
        self.assertEqual(projection.project({'configured': True, 'controllers': {'private': {}}, 'password': 'private',
            'views': [{'output': 'DP-1', 'mode': 'admin', 'url': 'https://foundry.example', 'unrelated': 'private'}]}),
            {'configured': True, 'views': [{'output': 'DP-1', 'mode': 'admin', 'url': 'https://foundry.example'}]})
