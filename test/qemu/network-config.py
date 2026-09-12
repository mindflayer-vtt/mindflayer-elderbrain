"""Validate candidates in an isolated Netplan root; never apply networking."""
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
from network_config import plan

original_text = subprocess.run(['netplan', 'get'], capture_output=True, text=True, check=True).stdout
original = yaml.safe_load(original_text)
requests = [
    {'interface': 'ens3', 'mode': 'static', 'address': '10.0.2.20', 'prefix': 24, 'gateway': '10.0.2.2', 'dns': ['10.0.2.3']},
    {'interface': 'ens3', 'mode': 'dhcp', 'dns': ['10.0.2.3']},
    {'interface': 'ens3', 'mode': 'dhcp', 'dns': []},
]
with tempfile.TemporaryDirectory(prefix='elderbrain-netplan-validation-') as directory:
    root = Path(directory)
    target = root / 'etc/netplan/test.yaml'
    target.parent.mkdir(parents=True)
    for request in requests:
        candidate = plan(original, request)
        target.write_text(json.dumps(candidate['configuration']))
        target.chmod(0o600)
        result = subprocess.run(['netplan', 'generate', '--root-dir', str(root)], capture_output=True, text=True)
        assert result.returncode == 0, 'Netplan rejected the isolated candidate'
        print(f"PASS: {request['mode']}, custom DNS={bool(request['dns'])}, warnings={len(candidate['warnings'])}", flush=True)
assert subprocess.run(['netplan', 'get'], capture_output=True, text=True, check=True).stdout == original_text
print('Host Netplan configuration unchanged; no network apply was performed.', flush=True)
