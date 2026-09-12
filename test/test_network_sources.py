import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('network_sources', ROOT / 'appliance/lib/network_sources.py')
module = importlib.util.module_from_spec(spec)
with patch.object(sys, 'path', [str(ROOT / 'appliance/lib'), *sys.path]):
    spec.loader.exec_module(module)


class NetworkSourcesTests(unittest.TestCase):
    def test_layer_precedence_and_filename_order(self):
        files = {'lib/netplan/10-base.yaml': b'', 'etc/netplan/10-base.yaml': b'',
                 'run/netplan/10-base.yaml': b'', 'etc/netplan/90-other.yaml': b''}
        self.assertEqual(module.effective_sources(files), ['run/netplan/10-base.yaml', 'etc/netplan/90-other.yaml'])
        with self.assertRaises(ValueError):
            module.effective_sources({'etc/netplan/../../secret.yaml': b''})

    def test_split_definition_is_replaced_without_touching_other_files(self):
        first = {'network': {'version': 2, 'ethernets': {'ens3': {'dhcp4': False, 'addresses': ['10.0.2.10/24']}, 'other': {'dhcp4': True}}}}
        second = {'network': {'ethernets': {'ens3': {'mtu': 1400, 'addresses': ['10.0.2.11/24']}}}}
        sources = {'etc/netplan/10-base.yaml': yaml.safe_dump(first).encode(),
                   'etc/netplan/90-extra.yaml': yaml.safe_dump(second).encode(),
                   'etc/netplan/20-unrelated.yaml': b'# Preserve these bytes\nnetwork:\n  version: 2\n'}
        merged = {'network': {'version': 2, 'ethernets': {'ens3': {'dhcp4': False, 'mtu': 1400, 'addresses': ['10.0.2.10/24', '10.0.2.11/24']}, 'other': {'dhcp4': True}}}}
        result = module.rewrite(sources, merged, {'interface': 'ens3', 'mode': 'static', 'address': '10.0.2.20', 'prefix': 24, 'gateway': '', 'dns': []})
        self.assertEqual(set(result['files']), {'etc/netplan/10-base.yaml', 'etc/netplan/90-extra.yaml'})
        early = yaml.safe_load(result['files']['etc/netplan/10-base.yaml']['after'])
        late = yaml.safe_load(result['files']['etc/netplan/90-extra.yaml']['after'])
        self.assertNotIn('ens3', early['network']['ethernets'])
        self.assertEqual(early['network']['ethernets']['other'], {'dhcp4': True})
        self.assertEqual(late['network']['ethernets']['ens3']['addresses'], ['10.0.2.20/24'])
        self.assertEqual(late['network']['ethernets']['ens3']['mtu'], 1400)
        self.assertEqual(result['files']['etc/netplan/10-base.yaml']['before'], sources['etc/netplan/10-base.yaml'])

    def test_transient_definition_is_not_written_into_persistent_configuration(self):
        document = {'network': {'version': 2, 'ethernets': {'ens3': {'dhcp4': True}}}}
        with self.assertRaisesRegex(ValueError, 'vendor or transient'):
            module.rewrite({'run/netplan/10-runtime.yaml': yaml.safe_dump(document).encode()}, document,
                           {'interface': 'ens3', 'mode': 'dhcp', 'dns': []})
