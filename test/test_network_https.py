import http.client
import json
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'appliance/lib'))
from network_confirmation import issue, verify
from network_https import ConfirmationServer
from network_transaction import NetworkTransaction


class NetworkHTTPSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.certs = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.certs.cleanup)
        root = Path(cls.certs.name)
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', str(root / 'key.pem'), '-out', str(root / 'cert.pem'),
                        '-days', '1', '-subj', '/CN=network-test', '-addext', 'subjectAltName=IP:127.0.0.1'],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cls.context.load_cert_chain(root / 'cert.pem', root / 'key.pem')
        cls.client_context = ssl.create_default_context(cafile=str(root / 'cert.pem'))

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        netplan = root / 'netplan'
        netplan.mkdir()
        (netplan / '50-test.yaml').write_bytes(b'before')
        self.links = {'interfaces': [{'name': 'ens3', 'internal': False,
                                     'addresses': [{'address': '127.0.0.1', 'source': 'DHCP'}]}]}
        self.store = NetworkTransaction(root / 'state', netplan, lambda: None,
            lambda proof, _public: verify(proof, self.store.read(), interfaces=lambda: self.links))
        self.token, binding = issue({'interface': 'ens3', 'mode': 'dhcp'})
        self.staged = self.store.stage({'50-test.yaml': {'before': b'before', 'after': b'after'}},
                                       'ens3', confirmation=binding)
        self.store.tick()
        self.server = ConfirmationServer(('127.0.0.1', 0), self.context, self.store)
        worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def send(self, value=None, path='/confirm', method='POST', headers=None):
        client = http.client.HTTPSConnection(*self.server.server_address, context=self.client_context, timeout=5)
        self.addCleanup(client.close)
        body = json.dumps(value if value is not None else {'id': self.staged['id'], 'token': self.token})
        if method != 'POST':
            body = None
        client.request(method, path, body, headers or {'Content-Type': 'application/json'})
        response = client.getresponse()
        return response.status, dict(response.getheaders()), response.read().decode()

    def test_real_tls_confirmation_is_one_time_and_keeps_token_out_of_response(self):
        status, headers, body = self.send()
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {'phase': 'confirmed'})
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertNotIn('Access-Control-Allow-Credentials', headers)
        self.assertNotIn(self.token, body)
        self.assertNotIn('confirmation', self.store.read())
        self.assertEqual(self.send()[0], 409)

    def test_invalid_tokens_and_forged_destination_headers_cannot_confirm(self):
        self.assertEqual(self.send({'id': self.staged['id'], 'token': 'x' * 43})[0], 409)
        self.links['interfaces'][0]['addresses'][0]['address'] = '10.0.2.20'
        self.assertEqual(self.send(headers={'Content-Type': 'application/json',
                              'Host': '10.0.2.20', 'X-Forwarded-Host': '10.0.2.20'})[0], 409)
        self.assertEqual(self.store.read()['phase'], 'pending')

    def test_body_path_and_content_type_are_restricted(self):
        for value in ({}, {'id': self.staged['id'], 'token': self.token, 'address': '127.0.0.1'},
                      {'id': self.staged['id'], 'token': 'x' * 600}):
            self.assertEqual(self.send(value)[0], 400)
        self.assertEqual(self.send(headers={'Content-Type': 'text/plain'})[0], 400)
        self.assertEqual(self.send(path='/confirm?token=not-accepted')[0], 404)
        self.assertEqual(self.store.read()['phase'], 'pending')

    def test_preflight_and_public_liveness_do_not_confirm_or_disclose_state(self):
        self.assertEqual(self.send(method='OPTIONS')[0], 200)
        status, _, body = self.send(method='GET', path='/')
        self.assertEqual(status, 200)
        self.assertNotIn(self.staged['id'], body)
        self.assertNotIn(self.token, body)
        self.assertEqual(self.store.read()['phase'], 'pending')

    def test_plain_http_cannot_reach_confirmation_handler(self):
        client = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        self.addCleanup(client.close)
        with self.assertRaises((OSError, http.client.HTTPException)):
            client.request('POST', '/confirm', json.dumps({'id': self.staged['id'], 'token': self.token}),
                           {'Content-Type': 'application/json'})
            client.getresponse()
        self.assertEqual(self.store.read()['phase'], 'pending')
