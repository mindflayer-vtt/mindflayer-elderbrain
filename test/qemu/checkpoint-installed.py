"""Installed disposable VM: prove actual writers stop during checkpoint capture."""
import json
from pathlib import Path
import subprocess
from snapshot_service import store
from backup_service import HostServices

def command(*args):
    return subprocess.check_output(args, text=True).strip()

assert command('lsblk', '-dn', '-o', 'SERIAL', '/dev/vda') == 'elderbrain-vm-test'
state = Path('/var/lib/mindflayer-elderbrain')
services = HostServices(Path('/opt/mindflayer-elderbrain'))
before = services.snapshot()
assert before['graphics'] and set(before['compose']) >= {'elderbrain-setup', 'mindflayer-server'}
snapshots = store()
original = snapshots.command
checked = []
def verify_paused(*args):
    if args[:3] == ('btrfs', 'subvolume', 'snapshot'):
        current = services.snapshot()
        assert not current['graphics'] and not current['compose'], 'Writers still running'
        assert json.loads((state / 'maintenance/maintenance.json').read_text())['state'] == 'working'
        checked.append(True)
    return original(*args)
snapshots.command = verify_paused
result = snapshots.create('manual')
assert checked == [True]
assert services.snapshot() == before, 'Original services not restored'
assert json.loads((state / 'maintenance/maintenance.json').read_text())['state'] == 'completed'
assert (snapshots.root / result['id'] / '.elderbrain-volume.json').read_bytes() == (state / '.elderbrain-volume.json').read_bytes()
assert result['id'] in {entry['id'] for entry in snapshots.list()}
print('PASS: installed services stopped during read-only capture and resumed; checkpoint ' + result['id'])
