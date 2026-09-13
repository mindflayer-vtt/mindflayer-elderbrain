from pathlib import Path
import ast
import io
import json
import socket
import socketserver
import struct
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


class ManagementRuntimeTests(unittest.TestCase):
    def test_clean_install_release_catalog_has_an_isolated_import_closure(self):
        root = Path(__file__).resolve().parents[1]
        installer = (root / 'provisioning/install.sh').read_text()
        modules = ('appliance_release', 'release_policy', 'release_recovery_status', 'release_catalog')
        for name in modules:
            self.assertIn(f'appliance/lib/{name}.py" "$RUNTIME/{name}.py', installer)
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            for name in modules:
                (runtime / f'{name}.py').write_bytes((root / 'appliance/lib' / f'{name}.py').read_bytes())
            subprocess.run([sys.executable, '-I', '-B', '-c',
                            'import sys;sys.path.insert(0,sys.argv[1]);import release_catalog', str(runtime)],
                           check=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=10)

    def test_host_job_bridge_bounds_payload_and_preserves_confirmations(self):
        # Load the actual handler class without executing the root-owned socket
        # server's installation/startup code on the development machine.
        source = Path(__file__).resolve().parents[1] / 'appliance/lib/management-server'
        tree = ast.parse(source.read_text())
        handler = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Handler')
        jobs = Mock()
        jobs.submit.return_value = {'id': 'a' * 32, 'state': 'queued'}
        namespace = dict(socketserver=socketserver, socket=socket, struct=struct, json=json,
                         subprocess=subprocess, JOBS=jobs, MANAGEMENT_GID=31338)
        exec(compile(ast.Module(body=[handler], type_ignores=[]), str(source), 'exec'), namespace)
        def send(data, uid=1000, gid=31338):
            instance = object.__new__(namespace['Handler'])
            instance.request = Mock()
            instance.request.getsockopt.return_value = struct.pack('3i', 1, uid, gid)
            instance.rfile, instance.wfile = io.BytesIO(data), io.BytesIO()
            instance.handle()
            return json.loads(instance.wfile.getvalue())
        selected = {'version': '1.2.3', 'manifestSha256': 'b' * 64,
                    'confirmUpdate': True, 'confirmDowntime': True}
        payload = json.dumps(selected).encode()
        data = f'update-start {len(payload)}\n'.encode() + payload
        self.assertTrue(send(data)['ok'])
        jobs.submit.assert_called_once_with('update', selected)
        jobs.submit.reset_mock()
        for invalid in (b'update-start 2049\n', b'update-start 0\n', b'update-start 10\n{}'):
            self.assertFalse(send(invalid)['ok'])
        self.assertFalse(send(data, gid=1000)['ok'])
        jobs.submit.assert_not_called()
        self.assertTrue(send(data, uid=999, gid=31338)['ok'])
        jobs.submit.assert_called_once_with('update', selected)
        jobs.submit.reset_mock()

        selected = {'action': 'shutdown', 'confirmPower': True}
        payload = json.dumps(selected).encode()
        self.assertTrue(send(f'power-start {len(payload)}\n'.encode() + payload)['ok'])
        jobs.submit.assert_called_once_with('power', selected)
        jobs.submit.reset_mock()

        selected = {'usbId': 'c' * 32, 'version': '1.2.3', 'revision': 4, 'adopt': False}
        payload = json.dumps(selected).encode()
        self.assertTrue(send(f'keypad-provision-start {len(payload)}\n'.encode() + payload)['ok'])
        jobs.submit.assert_called_once_with('keypad-provision', selected)

        jobs.directory.parent = Path('/test/state')
        power = types.SimpleNamespace(pending=Mock(return_value=True))
        with patch.dict(sys.modules, {'power_service': power}):
            status = send(b'power-status\n')
        self.assertEqual(json.loads(status['output']), {'pending': True})
        power.pending.assert_called_once_with(Path('/test/state'))

    def test_bind_mounted_socket_directory_survives_service_restart(self):
        root = Path(__file__).resolve().parents[1]
        unit = (root / 'provisioning/systemd/elderbrain-management.service').read_text()
        self.assertIn('RuntimeDirectory=elderbrain\n', unit)
        self.assertIn('RuntimeDirectoryPreserve=yes\n', unit)
        self.assertIn('- /run/elderbrain:/run/elderbrain', (root / 'compose/compose.yaml').read_text())

    def test_management_capability_uses_dedicated_group(self):
        root = Path(__file__).resolve().parents[1]
        server = (root / 'appliance/lib/management-server').read_text()
        dockerfile = (root / 'setup/Dockerfile').read_text()
        installer = (root / 'provisioning/install.sh').read_text()
        self.assertNotIn('uid not in (0, 1000)', server)
        self.assertIn('gid != MANAGEMENT_GID', server)
        self.assertIn('os.chown(SOCKET, 0, MANAGEMENT_GID)', server)
        self.assertIn('addgroup -S -g 31338 elderbrain-management', dockerfile)
        self.assertIn('USER node:elderbrain-management', dockerfile)
        self.assertIn('MANAGEMENT_GID=31338', installer)
        self.assertIn('groupadd --system --gid "$MANAGEMENT_GID" "$MANAGEMENT_GROUP"', installer)
