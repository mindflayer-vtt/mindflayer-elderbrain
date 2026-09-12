import copy
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'appliance/lib'))
from network_listener import Listener, PORT


class FakeServer:
    def __init__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs
        self.stopped = threading.Event()
        self.closed = False

    def serve_forever(self):
        self.stopped.wait()

    def shutdown(self):
        self.stopped.set()

    def server_close(self):
        self.closed = True


class NetworkListenerTests(unittest.TestCase):
    def setUp(self):
        self.record = {'id': 'a' * 32, 'phase': 'pending', 'interface': 'ens3',
                       'confirmation': {'mode': 'static', 'address': '10.0.2.20'}}
        self.store = Mock()
        self.store.read.side_effect = lambda: copy.deepcopy(self.record)
        self.store.expired.return_value = False
        self.links = {'interfaces': [{'name': 'ens3', 'internal': False,
                                     'addresses': [{'address': '10.0.2.20', 'source': 'Static'}]}]}
        self.tls, self.output = Mock(return_value='certificate'), Mock()
        self.factory = Mock(side_effect=FakeServer)
        self.listener = Listener(self.store, interfaces=lambda: self.links, tls=self.tls,
                                 server=self.factory, output=self.output)
        self.addCleanup(self.listener.close)

    def test_pending_binds_exact_address_and_interface_then_closes_on_confirmation(self):
        self.listener.tick()
        self.factory.assert_called_once_with(('10.0.2.20', PORT), 'certificate', self.store, interface='ens3')
        self.output.assert_called_with({'ready': True, 'id': 'a' * 32, 'url': f'https://10.0.2.20:{PORT}/confirm'})
        old = self.listener.server
        self.listener.tick()
        self.assertEqual(self.factory.call_count, 1)
        self.record['phase'] = 'confirmed'
        self.listener.tick()
        self.assertTrue(old.closed)
        self.assertIsNone(self.listener.active)
        self.output.assert_called_with({'ready': False})

    def test_expiry_rollback_or_missing_address_closes_listener(self):
        for change in (lambda: self.store.expired.configure_mock(return_value=True),
                       lambda: self.record.update(phase='rolling-back'),
                       lambda: self.links['interfaces'][0].update(addresses=[])):
            self.listener.tick()
            old = self.listener.server
            change()
            self.listener.tick()
            self.assertTrue(old.closed)
            self.store.expired.return_value = False
            self.record['phase'] = 'pending'
            self.links['interfaces'][0]['addresses'] = [{'address': '10.0.2.20', 'source': 'Static'}]

    def test_dhcp_discovers_unique_lease_and_rebinds_when_address_changes(self):
        self.record['confirmation'] = {'mode': 'dhcp', 'address': None}
        address = self.links['interfaces'][0]['addresses'][0]
        address['source'] = 'DHCP'
        self.listener.tick()
        old = self.listener.server
        address['address'] = '10.0.2.21'
        self.listener.tick()
        self.assertTrue(old.closed)
        self.assertEqual(self.listener.active[2], '10.0.2.21')
        self.links['interfaces'][0]['addresses'].append({'address': '10.0.2.22', 'source': 'DHCP'})
        self.listener.tick()
        self.assertIsNone(self.listener.active)

    def test_expiry_during_certificate_generation_does_not_open_port(self):
        self.tls.side_effect = lambda _address: self.record.update(phase='rolled-back')
        self.listener.tick()
        self.factory.assert_not_called()
        self.assertIsNone(self.listener.active)

    def test_certificate_or_discovery_failure_closes_and_stays_unavailable(self):
        self.tls.side_effect = ValueError('unavailable')
        with self.assertRaises(ValueError):
            self.listener.tick()
        self.factory.assert_not_called()
        self.output.assert_called_with({'ready': False})
