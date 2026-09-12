"""Read-only qualification of the administration upgrade on a fresh QEMU install.

Run as root after guest-checks.sh; never print bootstrap passwords or page titles.
"""
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess
import sys
import time

assert os.geteuid() == 0
assert subprocess.check_output(['systemd-detect-virt'], text=True).strip() in ('qemu', 'kvm')
sys.path.insert(0, '/opt/mindflayer-elderbrain')
from host_displays import discover as displays
from host_network import discover as network
from host_metrics import Metrics

for unit in ('elderbrain-admin-console', 'elderbrain-display-watchdog',
             'elderbrain-network-recovery', 'elderbrain-network-watchdog', 'elderbrain-network-confirmation'):
    subprocess.run(['systemctl', 'is-active', '--quiet', unit], check=True)
masked = subprocess.run(['systemctl', 'is-enabled', 'getty@tty2.service'], text=True, capture_output=True)
assert masked.stdout.strip() == 'masked'
assert json.loads(Path('/etc/opt/chrome/policies/managed/elderbrain.json').read_text())['PasswordManagerEnabled'] is False
secret = Path('/var/lib/mindflayer-elderbrain/elderbrain/secrets/initial-password')
if secret.exists():
    assert stat.S_IMODE(secret.stat().st_mode) == 0o600
    words = secret.read_text().strip().split('-')
    vocabulary = json.loads(Path('/opt/mindflayer-elderbrain/bootstrap-words.json').read_text())
    assert len(words) == 8 and all(word in vocabulary for word in words)
    credential_state = 'bootstrap format/permissions'
else:
    account = Path('/var/lib/mindflayer-elderbrain/elderbrain/secrets/admin.json')
    info = account.stat()
    record = json.loads(account.read_text())
    assert info.st_uid == 1000 and info.st_gid == 31338 and stat.S_IMODE(info.st_mode) == 0o600
    assert record['mustChange'] is False and record['verified'] is True
    credential_state = 'ready administrator state/permissions'
print(f'PASS: {credential_state}, tty2 service and managed password-saving policy.')

kiosk = pwd.getpwnam('elderbrain-kiosk')
assert subprocess.check_output(['loginctl', 'show-user', 'elderbrain-kiosk',
                                '--property=Linger', '--value'], text=True).strip() == 'yes'
subprocess.run(['systemctl', 'is-active', '--quiet', f'user@{kiosk.pw_uid}.service'], check=True)
projection = Path('/run/elderbrain-browser/config.json')
info = projection.stat()
assert info.st_uid == 0 and info.st_gid == kiosk.pw_gid and stat.S_IMODE(info.st_mode) == 0o640
assert set(json.loads(projection.read_text())) == {'configured', 'views'}
subprocess.run(['runuser', '-u', 'elderbrain-kiosk', '--', 'test', '-r', str(projection)], check=True)
outputs = displays()['outputs']
assert len([output for output in outputs if output['active']]) == 1
runtime = Path(f'/run/user/{kiosk.pw_uid}')
sockets = list(runtime.glob('sway-ipc.*.sock'))
assert len(sockets) == 1
tree = json.loads(subprocess.check_output(['runuser', '-u', 'elderbrain-kiosk', '--', 'swaymsg',
                  '-s', str(sockets[0]), '-t', 'get_tree'], text=True))
nodes, windows = [tree], []
while nodes:
    node = nodes.pop()
    nodes.extend(node.get('nodes', []) + node.get('floating_nodes', []))
    if (node.get('app_id') or '').startswith('elderbrain-view-'):
        windows.append(node)
assert len(windows) == 1 and windows[0]['visible'] is True
assert windows[0]['fullscreen_mode'] == 0, 'First boot should use a normal administration browser'
print('PASS: private root projection and exactly one visible, non-kiosk administration window.')

links = network()['interfaces']
assert any(link['name'] == 'ens3' and not link['internal'] and
           any(item['address'] == '10.0.2.15' and item['source'] == 'DHCP' for item in link['addresses']) for link in links)
metrics = Metrics()
metrics.sample()
time.sleep(1)
metrics.sample()
sample = metrics.snapshot()['history'][-1]
assert sample['cpu'] is not None and 0 <= sample['cpu'] <= 100
assert sample['ram']['total'] > 0 and sample['disks']
assert all(disk['total'] > 0 for disk in sample['disks'])
print('PASS: host DHCP attribution and actual CPU, RAM and filesystem readings.')
