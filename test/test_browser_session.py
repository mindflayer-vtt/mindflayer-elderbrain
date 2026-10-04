import importlib.util
import json
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

    def test_complete_connector_renumber_preserves_display_order(self):
        views = [
            {'output': 'DP-3', 'mode': 'admin', 'url': 'https://setup.example'},
            {'output': 'DP-4', 'mode': 'player', 'url': 'https://foundry.example'},
        ]
        outputs = [{'name': name, 'active': True} for name in ('DP-5', 'DP-6')]
        plan = module.plan({'configured': True, 'views': views}, outputs, 'token')
        self.assertEqual([(view['output'], view['mode']) for view in plan],
                         [('DP-5', 'admin'), ('DP-6', 'player')])

    def test_connector_renumber_does_not_cross_connector_families(self):
        views = [
            {'output': 'DP-3', 'mode': 'admin', 'url': 'https://setup.example'},
            {'output': 'DP-4', 'mode': 'player', 'url': 'https://foundry.example'},
        ]
        config = {'configured': True, 'views': views}
        single = module.plan(config, [{'name': 'DP-5', 'active': True}], 'token')
        self.assertEqual([(view['output'], view['mode']) for view in single], [('DP-5', 'admin')])
        mixed = [{'name': 'DP-5', 'active': True}, {'name': 'HDMI-A-1', 'active': True}]
        plan = module.plan(config, mixed, 'token')
        self.assertEqual([(view['output'], view['mode']) for view in plan], [('DP-5', 'admin')])

    def test_admin_fails_over_to_only_remaining_screen(self):
        views = [
            {'output': 'DP-3', 'mode': 'admin', 'url': 'https://setup.example'},
            {'output': 'DP-4', 'mode': 'player', 'url': 'https://foundry.example'},
        ]
        config = {'configured': True, 'views': views}
        plan = module.plan(config, [{'name': 'DP-4', 'active': True}], 'token')
        self.assertEqual([(view['index'], view['output'], view['mode']) for view in plan],
                         [(0, 'DP-4', 'admin')])
        plan = module.plan(config, [{'name': 'DP-8', 'active': True}], 'token')
        self.assertEqual([(view['index'], view['output'], view['mode']) for view in plan],
                         [(0, 'DP-8', 'admin')])

    def test_cursor_defaults_to_centre_of_first_connected_admin_display(self):
        desired = {
            0: {'index': 0, 'output': 'DP-5', 'mode': 'admin'},
            1: {'index': 1, 'output': 'DP-6', 'mode': 'player'},
        }
        outputs = [
            {'name': 'DP-6', 'active': True,
             'rect': {'x': 0, 'y': 0, 'width': 1920, 'height': 1080}},
            {'name': 'DP-5', 'active': True,
             'rect': {'x': 1920, 'y': 0, 'width': 1920, 'height': 1080}},
        ]
        self.assertEqual(module.admin_cursor_target(desired, outputs), ('DP-5', 2880, 540))
        desired[0]['mode'] = 'player'
        self.assertIsNone(module.admin_cursor_target(desired, outputs))
        desired[0]['mode'] = 'admin'
        outputs[1]['rect']['width'] = 0
        self.assertIsNone(module.admin_cursor_target(desired, outputs))

    def test_resolution_uses_highest_mode_by_default_and_refresh_for_selection(self):
        output = {'name': 'DP-5', 'active': True, 'modes': [
            {'width': 1920, 'height': 1080, 'refresh': 59940},
            {'width': 1920, 'height': 1080, 'refresh': 60000},
            {'width': 1280, 'height': 720, 'refresh': 120000},
        ]}
        self.assertEqual(module.preferred_mode({'resolution': ''}, output), (1920, 1080, 60000))
        self.assertEqual(module.preferred_mode({'resolution': '1280x720'}, output), (1280, 720, 120000))
        self.assertEqual(module.preferred_mode({'resolution': '3840x2160'}, output), (1920, 1080, 60000))

    def test_resolution_applies_only_an_advertised_changed_mode(self):
        desired = {0: {'output': 'DP-5', 'resolution': '1280x720'}}
        outputs = [{'name': 'DP-5', 'active': True,
                    'current_mode': {'width': 1920, 'height': 1080, 'refresh': 60000},
                    'modes': [{'width': 1280, 'height': 720, 'refresh': 120000}]}]
        response = SimpleNamespace(stdout='[{"success":true}]')
        with patch.object(module.subprocess, 'run', return_value=response) as run:
            self.assertTrue(module.apply_output_modes(desired, outputs))
        self.assertEqual(run.call_args.args[0],
                         ['swaymsg', '-r', 'output "DP-5" mode 1280x720@120.000Hz'])
        outputs[0]['current_mode'] = {'width': 1280, 'height': 720, 'refresh': 120000}
        with patch.object(module.subprocess, 'run') as run:
            self.assertFalse(module.apply_output_modes(desired, outputs))
            run.assert_not_called()

    def test_cursor_placement_is_best_effort_and_uses_fixed_seat(self):
        response = SimpleNamespace(stdout='[{"success":true}]')
        with patch.object(module.subprocess, 'run', return_value=response) as run:
            self.assertTrue(module.move_cursor(('DP-5', 2880, 540)))
        self.assertEqual(run.call_args.args[0],
                         ['swaymsg', '-r',
                          'focus output "DP-5"; seat seat0 cursor set 2880 540'])
        with patch.object(module.subprocess, 'run', side_effect=OSError):
            self.assertFalse(module.move_cursor(('DP-5', 2880, 540)))

    def test_cursor_waits_until_all_planned_windows_are_mapped(self):
        desired = {0: {'mode': 'admin'}, 1: {'mode': 'player'}}
        partial = SimpleNamespace(stdout='{"nodes":[{"app_id":"elderbrain-view-0"}]}')
        complete = SimpleNamespace(stdout=(
            '{"nodes":[{"app_id":"elderbrain-view-0"}],'
            '"floating_nodes":[{"nodes":[{"app_id":"elderbrain-view-1"}]}]}'))
        with patch.object(module.subprocess, 'run', return_value=partial):
            self.assertFalse(module.views_mapped(desired))
        with patch.object(module.subprocess, 'run', return_value=complete) as run:
            self.assertTrue(module.views_mapped(desired))
        self.assertEqual(run.call_args.args[0], ['swaymsg', '-r', '-t', 'get_tree'])

    def test_window_output_mapping_and_hotplug_repair(self):
        tree = {'nodes': [
            {'type': 'output', 'name': 'DP-6', 'nodes': [
                {'nodes': [{'app_id': 'elderbrain-view-0'}]}]},
            {'type': 'output', 'name': 'DP-5', 'nodes': [
                {'floating_nodes': [{'app_id': 'elderbrain-view-1'}]}]},
        ]}
        response = SimpleNamespace(stdout=json.dumps(tree))
        with patch.object(module.subprocess, 'run', return_value=response):
            self.assertEqual(module.window_outputs(), {0: 'DP-6', 1: 'DP-5'})

        response.stdout = '[{"success":true},{"success":true}]'
        view = {'index': 0, 'output': 'DP-5', 'mode': 'admin'}
        with patch.object(module.subprocess, 'run', return_value=response) as run:
            self.assertTrue(module.place_view(view))
        self.assertEqual(run.call_args.args[0], ['swaymsg', '-r',
            '[app_id="elderbrain-view-0"] move container to output "DP-5"; '
            '[app_id="elderbrain-view-0"] fullscreen disable'])

        with patch.object(module.subprocess, 'run', return_value=response) as run:
            self.assertTrue(module.place_view({**view, 'mode': 'player'}, future=True))
        self.assertIn('for_window [app_id="elderbrain-view-0"]', run.call_args.args[0][2])
        self.assertIn('fullscreen enable', run.call_args.args[0][2])

    def test_small_chrome_auxiliary_window_floats_without_resizing_main_view(self):
        main = {'type': 'con', 'id': 5, 'app_id': 'elderbrain-view-0',
                'name': 'Foundry - Google Chrome', 'floating': 'auto_off',
                'geometry': {'width': 1904, 'height': 1031}}
        pip = {'type': 'con', 'id': 6, 'app_id': 'elderbrain-view-0',
               'name': 'An arbitrary Spotify track title', 'floating': 'auto_off',
               'geometry': {'width': 300, 'height': 334}}
        tree = {'nodes': [{'type': 'output', 'name': 'DP-1', 'nodes': [
            {'type': 'workspace', 'nodes': [main, pip]}]}]}
        desired = {0: {'mode': 'admin', 'output': 'DP-1'}}
        self.assertEqual(module.auxiliary_window_ids(tree, desired), [6])
        response = SimpleNamespace(stdout='[{"success":true},{"success":true}]')
        with patch.object(module.subprocess, 'run', return_value=response) as run:
            self.assertTrue(module.float_auxiliary_windows(tree, desired))
        self.assertEqual(run.call_args.args[0], ['swaymsg', '-r',
            '[con_id=6] fullscreen disable; [con_id=6] floating enable'])

        pip['floating'] = 'user_on'
        self.assertEqual(module.auxiliary_window_ids(tree, desired), [])
        pip['floating'] = 'auto_off'
        pip['geometry'] = {'width': 1800, 'height': 900}
        self.assertEqual(module.auxiliary_window_ids(tree, desired), [])

    def test_auxiliary_window_detection_requires_a_managed_main_and_valid_geometry(self):
        small = {'type': 'con', 'id': 9, 'app_id': 'elderbrain-view-0',
                 'floating': 'auto_off', 'geometry': {'width': 300, 'height': 300}}
        main = {'type': 'con', 'id': 8, 'app_id': 'elderbrain-view-0',
                'floating': 'auto_off', 'geometry': {'width': 1600, 'height': 900}}
        self.assertEqual(module.auxiliary_window_ids({'nodes': [small]}, {0: {}}), [])
        self.assertEqual(module.auxiliary_window_ids({'nodes': [main, small]}, {1: {}}), [])
        small['geometry'] = {'width': -1, 'height': 300}
        self.assertEqual(module.auxiliary_window_ids({'nodes': [main, small]}, {0: {}}), [])
        small['geometry'] = {'width': 300, 'height': 300}
        small['app_id'] = 'unmanaged-window'
        self.assertEqual(module.auxiliary_window_ids({'nodes': [main, small]}, {0: {}}), [])

    def test_one_renumbered_screen_recovers_without_moving_connected_admin(self):
        views = [
            {'output': 'DP-3', 'mode': 'admin', 'url': 'https://setup.example'},
            {'output': 'DP-4', 'mode': 'player', 'url': 'https://foundry.example'},
        ]
        outputs = [{'name': name, 'active': True} for name in ('DP-3', 'DP-8')]
        plan = module.plan({'configured': True, 'views': views}, outputs, 'token')
        self.assertEqual([(view['output'], view['mode']) for view in plan],
                         [('DP-3', 'admin'), ('DP-8', 'player')])

    def test_monitor_identity_wins_when_connectors_swap(self):
        admin_monitor = {'make': 'Desk', 'model': 'Panel', 'serial': 'admin'}
        player_monitor = {'make': 'Acer', 'model': 'Projector', 'serial': 'player'}
        views = [
            {'output': 'DP-3', 'displayId': module.monitor_id(admin_monitor),
             'mode': 'admin', 'url': 'https://setup.example'},
            {'output': 'DP-4', 'displayId': module.monitor_id(player_monitor),
             'mode': 'player', 'url': 'https://foundry.example'},
        ]
        outputs = [
            {'name': 'DP-3', 'active': True, **player_monitor},
            {'name': 'DP-4', 'active': True, **admin_monitor},
        ]
        plan = module.plan({'configured': True, 'views': views}, outputs, 'token')
        self.assertEqual([(view['output'], view['mode']) for view in plan],
                         [('DP-4', 'admin'), ('DP-3', 'player')])

    def test_virtual_terminal_output_suspension_keeps_existing_views(self):
        self.assertTrue(module.outputs_suspended([], {0: object()}))
        self.assertFalse(module.outputs_suspended([], {}))
        self.assertFalse(module.outputs_suspended(
            [{'name': 'DP-1', 'active': True}], {0: object()}))

    def test_actionable_beamer_errors_wait_for_configuration_change(self):
        for state in module.TERMINAL_STATES:
            self.assertEqual(module.next_retry(state, 100), float('inf'))
        for state in ('unavailable', 'world-not-running', 'module-unavailable',
                      'canvas-unavailable', 'stopped'):
            self.assertEqual(module.next_retry(state, 100), 160)

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
        self.assertIn('viewport: config.headless ? { width: 1280, height: 720 } : null', worker)
        self.assertNotIn('--disable-session-crashed-bubble', worker)
        self.assertEqual(plan[0]['urls'][-1], 'https://notes.example')
        self.assertEqual(len(plan[1]['urls']), 1)
        self.assertNotEqual(next(arg for arg in admin if arg.startswith('--user-data-dir')), next(arg for arg in player if arg.startswith('--user-data-dir')))

    def test_player_statuses_use_offline_instruction_page_and_isolated_profile(self):
        view = {'index': 1, 'output': 'DP-2', 'mode': 'player', 'urls': ['https://foundry.example']}
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary)
            for state, expected in [('pairing-required', 'configure the Beamer credentials'),
                                    ('world-not-running', 'launch the configured Foundry world'),
                                    ('permission-review-required', 'additional Foundry permissions'),
                                    ('module-review-required', 'Mindflayer module Beamer user settings')]:
                args = module.player_status_args('chrome', view, runtime, state)
                page = runtime / 'beamer-status-1.html'
                self.assertEqual(page.stat().st_mode & 0o777, 0o600)
                self.assertIn(expected, page.read_text())
                self.assertIn('--kiosk', args)
                self.assertIn(f'--user-data-dir={runtime}/profile-1-status', args)
                self.assertIn(page.as_uri(), args)
                self.assertNotIn('https://foundry.example', args)
            with self.assertRaises(ValueError):
                module.player_status_args('chrome', view, runtime, 'private-state')

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
        self.assertIn('default_border none', (ROOT / 'provisioning/graphics/sway.conf').read_text())
        self.assertIn('default_floating_border none', (ROOT / 'provisioning/graphics/sway.conf').read_text())
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
        display_id = 'monitor-' + 'a' * 64
        self.assertEqual(projection.project({'configured': True, 'controllers': {'private': {}}, 'password': 'private',
            'views': [{'output': 'DP-1', 'displayId': display_id, 'mode': 'admin',
                       'resolution': '1920x1080', 'url': 'https://foundry.example', 'unrelated': 'private'}]}),
            {'configured': True, 'views': [{'output': 'DP-1', 'displayId': display_id,
                                            'resolution': '1920x1080', 'mode': 'admin',
                                            'url': 'https://foundry.example'}]})
