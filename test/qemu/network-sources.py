"""Prove source replacement against Netplan itself, entirely in temporary roots."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import yaml

if os.geteuid() != 0 or subprocess.run(['systemd-detect-virt', '--vm'], capture_output=True, text=True).stdout.strip() not in ('kvm', 'qemu'):
    raise SystemExit('Run only in the disposable QEMU appliance VM')
sys.path.insert(0, '/opt/mindflayer-elderbrain')
from network_sources import rewrite


def netplan(root, operation):
    result = subprocess.run(['netplan', operation, '--root-dir', str(root)], capture_output=True, text=True)
    assert result.returncode == 0, 'Isolated Netplan validation failed'
    return yaml.safe_load(result.stdout) if operation == 'get' else None


def check(sources, title):
    with tempfile.TemporaryDirectory(prefix='elderbrain-netplan-sources-') as directory:
        root = Path(directory)
        for name, value in sources.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value)
            target.chmod(0o600)
        original = netplan(root, 'get')
        prepared = rewrite(sources, original, {'interface': 'ens3', 'mode': 'static', 'address': '10.0.2.20',
                                             'prefix': 24, 'gateway': '10.0.2.2', 'dns': ['10.0.2.3']})
        for name, change in prepared['files'].items():
            assert (root / name).read_bytes() == change['before']
            (root / name).write_bytes(change['after'])
        netplan(root, 'generate')
        assert netplan(root, 'get') == prepared['configuration'], 'Merged candidate differs from intended configuration'
        for name in set(sources) - set(prepared['files']):
            assert (root / name).read_bytes() == sources[name]
        for name, change in prepared['files'].items():
            (root / name).write_bytes(change['before'])
        assert netplan(root, 'get') == original
        print('PASS: ' + title + '; exact merged candidate and byte-preserving restore', flush=True)


actual = {str(path.relative_to('/')): path.read_bytes() for base in ('/lib/netplan', '/etc/netplan', '/run/netplan')
          for path in Path(base).glob('*.yaml')}
check(actual, 'appliance file origins')
check({
    'etc/netplan/10-base.yaml': json.dumps({'network': {'version': 2, 'ethernets': {
        'ens3': {'addresses': ['10.0.2.10/24']}, 'other': {'dhcp4': True}}}}).encode(),
    'etc/netplan/90-extra.yaml': json.dumps({'network': {'ethernets': {'ens3': {'mtu': 1400, 'addresses': ['10.0.2.11/24']}}}}).encode(),
    'etc/netplan/20-untouched.yaml': b'# Unrelated file, preserve bytes\nnetwork:\n  version: 2\n',
}, 'split interface definition')
assert all(Path('/' + name).read_bytes() == value for name, value in actual.items())
print('VM configuration unchanged; no network apply performed.', flush=True)
