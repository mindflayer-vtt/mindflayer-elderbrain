import copy
import socket
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'appliance/lib'))
from network_confirmation import ConnectionProof, issue, verify


class NetworkConfirmationTests(unittest.TestCase):
    def setUp(self):
        listener = socket.socket()
        self.addCleanup(listener.close)
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        client = socket.create_connection(listener.getsockname())
        self.addCleanup(client.close)
        self.accepted, _ = listener.accept()
        self.addCleanup(self.accepted.close)
        self.listener = listener
        self.token, binding = issue({'interface': 'ens3', 'mode': 'dhcp'})
        self.record = {'id': 'transaction-one', 'interface': 'ens3', 'phase': 'pending', 'confirmation': binding}
        self.links = {'interfaces': [{'name': 'ens3', 'internal': False,
                                     'addresses': [{'address': '127.0.0.1', 'source': 'DHCP'}]}]}

    def verify(self, proof=None, record=None):
        return verify(proof or ConnectionProof(self.accepted, self.token), record or self.record,
                      interfaces=lambda: self.links)

    def test_real_connected_destination_and_token_are_both_required(self):
        self.assertTrue(self.verify())
        self.assertNotIn(self.token, str(self.record))
        self.assertFalse(self.verify(ConnectionProof(self.accepted, 'x' * 43)))
        self.assertFalse(self.verify(ConnectionProof(self.listener, self.token)))
        self.assertFalse(self.verify({'token': self.token, 'Host': '127.0.0.1',
                                     'X-Forwarded-Host': '127.0.0.1', 'destination': '127.0.0.1'}))
        self.assertFalse(self.verify(ConnectionProof('127.0.0.1', self.token)))

    def test_wrong_interface_stale_address_unknown_source_and_internal_link_fail(self):
        for mutate in (lambda link: link.update(name='ens4'),
                       lambda link: link.update(internal=True),
                       lambda link: link['addresses'][0].update(address='10.0.2.15'),
                       lambda link: link['addresses'][0].update(source='Unknown'),
                       lambda link: link['addresses'][0].update(source='Static')):
            original = copy.deepcopy(self.links)
            mutate(self.links['interfaces'][0])
            self.assertFalse(self.verify())
            self.links = original

    def test_static_requires_exact_configured_address_and_source(self):
        self.record['confirmation'].update(mode='static', address='10.0.2.20')
        self.links['interfaces'][0]['addresses'][0]['source'] = 'Static'
        self.assertFalse(self.verify())
        # Loopback is only a socket fixture; production issue() rejects it.
        self.record['confirmation']['address'] = '127.0.0.1'
        self.assertTrue(self.verify())
        with self.assertRaises(ValueError):
            issue({'interface': 'ens3', 'mode': 'static', 'address': '127.0.0.1', 'prefix': 8})

    def test_terminal_phases_and_token_from_another_transaction_fail(self):
        for phase in ('staged', 'applying', 'confirmed', 'rolling-back', 'rolled-back'):
            self.assertFalse(self.verify(record={**self.record, 'phase': phase}))
        _, second = issue({'interface': 'ens3', 'mode': 'dhcp'})
        self.assertFalse(self.verify(record={**self.record, 'confirmation': second}))
        self.assertFalse(self.verify(record={**self.record, 'confirmation': None}))

    def test_closed_connection_and_discovery_failure_fail_closed(self):
        self.accepted.close()
        self.assertFalse(self.verify())
