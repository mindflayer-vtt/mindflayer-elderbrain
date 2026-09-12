"""Read-only qualification checks on an installed persistent-storage guest."""

import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, '/opt/mindflayer-elderbrain')
from storage_guard import check, read_identity

STATE = Path('/var/lib/mindflayer-elderbrain')
RUNTIME = Path('/opt/mindflayer-elderbrain')
check()
identity = read_identity('/etc/elderbrain/storage.json')
for name, alias in {'netplan': '/etc/netplan', 'ssh-server': '/etc/ssh',
                    'ssh-root': '/root/.ssh', 'ssh-admin': '/home/elderbrain-installer/.ssh'}.items():
    assert (STATE / 'host' / name).samefile(alias), f'Incorrect persistent alias: {name}'
for name in ('appliance.env', 'sway.conf'):
    alias = RUNTIME / name
    assert alias.is_symlink(), f'Missing runtime settings link: {name}'
    assert alias.resolve() == STATE / 'host/runtime' / name
for name in ('foundry', 'elderbrain', 'mindflayer', 'traefik', 'firmware', 'browser',
             'backups', 'keypad-installations'):
    assert (STATE / name).is_dir(), f'Missing data directory: {name}'
    assert (STATE / name).stat().st_dev == STATE.stat().st_dev, f'Nonpersistent data: {name}'
foundry = (STATE / 'foundry').stat()
assert (foundry.st_uid, foundry.st_gid) == (1000, 1000), 'Foundry data must belong to the container user'
subprocess.run(['setpriv', '--reuid=1000', '--regid=1000', '--clear-groups',
                'sh', '-c', 'test -r "$1" && test -w "$1" && test -x "$1"',
                'foundry-volume-check', str(STATE / 'foundry')], check=True)
root = json.loads(subprocess.check_output([
    'findmnt', '--json', '--mountpoint', '/', '--output', 'UUID,FSTYPE'], text=True))['filesystems'][0]
assert root['uuid'] != identity['data_uuid'], 'OS and data must be separate filesystems'
assert root['fstype'] == 'ext4'
subprocess.run(['systemctl', 'is-active', '--quiet', 'elderbrain-storage.service'], check=True)
for unit in ('docker', 'elderbrain-stack', 'elderbrain-management', 'elderbrain-network-recovery'):
    requires = subprocess.check_output(['systemctl', 'show', unit, '--property=Requires', '--value'], text=True).split()
    assert 'elderbrain-storage.service' in requires, f'Missing storage dependency: {unit}'
print('Persistent storage: identity, OS separation, data directories, aliases and service dependencies verified')
