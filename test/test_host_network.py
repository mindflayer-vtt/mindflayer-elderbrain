import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('host_network', ROOT / 'appliance/lib/host_network.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class HostNetworkTests(unittest.TestCase):
    def test_sources_are_verified_per_address_and_containers_are_marked(self):
        addresses = [{'family': 'inet', 'local': address, 'prefixlen': 24, 'scope': 'global'}
                     for address in ('10.0.96.125', '10.0.96.126', '10.0.96.127')]
        links = [{'ifname': 'lo', 'flags': ['LOOPBACK']},
                 {'ifname': 'docker0', 'ifindex': 3, 'addr_info': []},
                 {'ifname': 'eno1', 'ifindex': 2, 'operstate': 'UP', 'addr_info': addresses}]
        networkd = {'Interfaces': [{'Index': 2, 'Addresses': [
            {'Family': 2, 'Address': [10, 0, 96, 125], 'ConfigSource': 'DHCPv4'},
            {'Family': 2, 'Address': [10, 0, 96, 126], 'ConfigSource': 'static'}],
            'DNS': [{'Family': 2, 'Address': [10, 0, 96, 1]}]}]}
        result = module.normalize(links, [{'dev': 'eno1', 'dst': 'default', 'gateway': '10.0.96.1'}], networkd)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['name'], 'eno1')
        self.assertEqual([address['source'] for address in result[0]['addresses']], ['DHCP', 'Static', 'Unknown'])
        self.assertEqual(result[0]['dns'], ['10.0.96.1'])
        self.assertTrue(result[0]['defaultRoute'])
        self.assertTrue(result[1]['internal'])

    def test_metadata_failure_preserves_kernel_addresses_without_guessing(self):
        links = [{'ifname': 'eno1', 'ifindex': 2, 'addr_info': [
            {'family': 'inet', 'local': '10.0.0.2', 'prefixlen': 24, 'dynamic': True}]}]
        with patch.object(module, 'command', side_effect=[links, [], subprocess.TimeoutExpired('networkctl', 5)]):
            result = module.discover()
        self.assertEqual(result['interfaces'][0]['addresses'][0]['source'], 'Unknown')
        self.assertEqual(len(result['errors']), 1)
        with patch.object(module, 'command', side_effect=OSError()):
            with self.assertRaises(OSError):
                module.discover()

    def test_invalid_addresses_are_rejected(self):
        for value in (None, 'not-an-ip', [256, 0, 0, 1], [1, 2], '::1'):
            self.assertIsNone(module.ipv4(value))
