from pathlib import Path
import ast
import io
import json
import socket
import socketserver
import struct
import subprocess
import unittest
from unittest.mock import Mock


class ManagementRuntimeTests(unittest.TestCase):
    def test_update_bridge_bounds_payload_and_preserves_confirmations(self):
        # Load the actual handler class without executing the root-owned socket
        # server's installation/startup code on the development machine.
        source = Path(__file__).resolve().parents[1] / 'appliance/lib/management-server'
        tree = ast.parse(source.read_text())
        handler = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Handler')
        jobs = Mock()
        jobs.submit.return_value = {'id': 'a' * 32, 'state': 'queued'}
        namespace = dict(socketserver=socketserver, socket=socket, struct=struct, json=json,
                         subprocess=subprocess, JOBS=jobs)
        exec(compile(ast.Module(body=[handler], type_ignores=[]), str(source), 'exec'), namespace)
        def send(data, uid=1000):
            instance = object.__new__(namespace['Handler'])
            instance.request = Mock()
            instance.request.getsockopt.return_value = struct.pack('3i', 1, uid, uid)
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
        self.assertFalse(send(data, uid=999)['ok'])
        jobs.submit.assert_not_called()

    def test_bind_mounted_socket_directory_survives_service_restart(self):
        root = Path(__file__).resolve().parents[1]
        unit = (root / 'provisioning/systemd/elderbrain-management.service').read_text()
        self.assertIn('RuntimeDirectory=elderbrain\n', unit)
        self.assertIn('RuntimeDirectoryPreserve=yes\n', unit)
        self.assertIn('- /run/elderbrain:/run/elderbrain', (root / 'compose/compose.yaml').read_text())
