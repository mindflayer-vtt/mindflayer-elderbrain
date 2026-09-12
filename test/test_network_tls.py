from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'appliance/lib'))
from network_tls import context


class NetworkTLSTests(unittest.TestCase):
    def test_leaf_uses_existing_ca_and_exact_new_ip_without_retaining_private_leaf(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                            '-keyout', str(root / 'ca.key'), '-out', str(root / 'ca.crt'),
                            '-days', '1', '-subj', '/CN=network-test-CA',
                            '-addext', 'basicConstraints=critical,CA:TRUE',
                            '-addext', 'keyUsage=critical,keyCertSign,cRLSign'],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            original = {p.name: p.read_bytes() for p in root.iterdir()}
            server_context = context('10.0.2.20', root)
            self.assertEqual(server_context.minimum_version, ssl.TLSVersion.TLSv1_2)
            listener = socket.socket()
            self.addCleanup(listener.close)
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            errors = []
            def serve():
                try:
                    connection, _ = listener.accept()
                    with server_context.wrap_socket(connection, server_side=True) as secure:
                        secure.sendall(b'ok')
                except Exception as error:
                    errors.append(error)
            worker = threading.Thread(target=serve, daemon=True)
            worker.start()
            trusted = ssl.create_default_context(cafile=str(root / 'ca.crt'))
            with socket.create_connection(listener.getsockname(), timeout=5) as connection:
                with trusted.wrap_socket(connection, server_hostname='10.0.2.20') as secure:
                    self.assertEqual(secure.recv(2), b'ok')
                    self.assertEqual(secure.getpeercert()['subjectAltName'], (('IP Address', '10.0.2.20'),))
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, original)

    def test_invalid_addresses_are_rejected_before_certificate_work(self):
        for address in ('127.0.0.1', '0.0.0.0', 'not-an-ip', '10.0.2.20,DNS:attacker'):
            with self.assertRaises(ValueError):
                context(address, '/missing-test-ca')
