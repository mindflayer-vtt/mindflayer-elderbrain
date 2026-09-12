import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('network_config', ROOT / 'appliance/lib/network_config.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class NetworkConfigTests(unittest.TestCase):
    def setUp(self):
        self.document = {'network': {'version': 2, 'renderer': 'networkd', 'ethernets': {
            'primary': {'match': {'macaddress': '52:54:00:12:34:56'}, 'set-name': 'ens3', 'dhcp4': True, 'dhcp6': True,
                'addresses': ['10.0.2.15/24', {'2001:db8::1/64': {'lifetime': 0}}],
                'dhcp4-overrides': {'route-metric': 100}, 'mtu': 1400,
                'nameservers': {'addresses': ['10.0.2.3', '2001:db8::53'], 'search': ['table.example']},
                'routes': [{'to': 'default', 'via': '10.0.2.2', 'metric': 100},
                    {'to': 'default', 'via': '2001:db8::2'}, {'to': '10.9.0.0/16', 'via': '10.0.2.2'},
                    {'to': 'default', 'via': '10.0.2.3', 'table': 100}]},
            'other': {'dhcp4': True}}, 'wifis': {'wlan0': {'access-points': {'private': {'password': 'preserved'}}}}}}
        self.static = {'interface': 'ens3', 'mode': 'static', 'address': '10.0.2.20', 'prefix': 24, 'gateway': '10.0.2.1', 'dns': ['1.1.1.1']}

    def test_static_preserves_unrelated_network_state_and_input(self):
        before = copy.deepcopy(self.document)
        result = module.edit(self.document, self.static)
        self.assertEqual(self.document, before)
        old = self.document['network']['ethernets']['primary']
        target = result['network']['ethernets']['primary']
        for key in ('match', 'set-name', 'dhcp6', 'mtu', 'dhcp4-overrides'):
            self.assertEqual(target[key], old[key])
        self.assertEqual(target['addresses'], [{'2001:db8::1/64': {'lifetime': 0}}, '10.0.2.20/24'])
        self.assertEqual(target['routes'][:-1], old['routes'][1:])
        self.assertEqual(target['routes'][-1], {'to': 'default', 'via': '10.0.2.1', 'metric': 100})
        self.assertEqual(target['nameservers'], {'addresses': ['2001:db8::53', '1.1.1.1'], 'search': ['table.example']})
        self.assertEqual(result['network']['wifis'], before['network']['wifis'])
        self.assertEqual(result['network']['ethernets']['other'], before['network']['ethernets']['other'])

    def test_dhcp_removes_static_ipv4_but_preserves_ipv6_and_policy_routes(self):
        result = module.edit(self.document, {'interface': 'ens3', 'mode': 'dhcp', 'dns': []})
        target = result['network']['ethernets']['primary']
        self.assertTrue(target['dhcp4'])
        self.assertEqual(len(target['addresses']), 1)
        self.assertEqual(target['dhcp4-overrides'], {'route-metric': 100, 'use-dns': True})
        self.assertEqual(len(target['routes']), 3)
        override = module.edit(self.document, {'interface': 'ens3', 'mode': 'dhcp', 'dns': ['1.1.1.1']})
        self.assertFalse(override['network']['ethernets']['primary']['dhcp4-overrides']['use-dns'])
        self.assertFalse(override['network']['ethernets']['primary']['dhcp6-overrides']['use-dns'])
        self.assertEqual(len(module.plan(self.document, {'interface': 'ens3', 'mode': 'dhcp', 'dns': ['1.1.1.1']})['warnings']), 1)
        self.document['network']['renderer'] = 'NetworkManager'
        independent = module.plan(self.document, {'interface': 'ens3', 'mode': 'dhcp', 'dns': ['1.1.1.1']})
        self.assertNotIn('dhcp6-overrides', independent['configuration']['network']['ethernets']['primary'])
        self.assertEqual(independent['warnings'], [])

    def test_bad_addresses_gateway_prefix_and_interface_fail(self):
        for change in ({'address': '127.0.0.1'}, {'prefix': True}, {'prefix': 33}, {'address': '10.0.2.255'},
                       {'gateway': '10.8.0.1'}, {'gateway': '10.0.2.20'}, {'dns': ['::1']}, {'interface': 'ens3;bad'},
                       {'mode': 'other'}, {'extra': 'forbidden'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                module.edit(self.document, {**self.static, **change})

    def test_ambiguous_mapping_and_family_are_not_guessed(self):
        self.document['network']['ethernets']['other']['set-name'] = 'ens3'
        with self.assertRaisesRegex(ValueError, 'unambiguously'):
            module.edit(self.document, self.static)
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            module.main_ipv4_default({'to': 'default'})
