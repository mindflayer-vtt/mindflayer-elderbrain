"""Install boot prerequisites only on the explicitly identified disposable VM."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'appliance/lib'))
from backup_service import Maintenance
from provisioning.recovery_bootstrap import provision
from release_bootstrap import UNITS, WRITERS
from restore_service import persistent_identity


def command(*args):
    return subprocess.check_output(args, text=True, timeout=60).strip()


assert os.geteuid() == 0
assert Path('/sys/class/dmi/id/product_name').read_text().startswith('Standard PC')
assert command('lsblk', '-dn', '-o', 'SERIAL', '/dev/vda') == 'elderbrain-vm-test'
state = Path('/var/lib/mindflayer-elderbrain')
identity = persistent_identity(state, Path('/'))
assert identity is not None
previous = Maintenance(state / 'maintenance', None).previous()
assert previous.get('state') in (None, 'completed', 'failed', 'recovered', 'rolled-back')
result = provision()
assert result['state'] == 'installed' and result['activationReady'] is False
command('systemd-analyze', 'verify', '--man=no', '--generators=yes',
        *UNITS, *WRITERS, 'elderbrain-storage.service')
command('/usr/bin/python3', '-I', '-B', '/usr/libexec/elderbrain-recovery.py', 'storage')
# No pending update exists: both real entry points must be harmless no-ops.
for phase in ('files', 'finish'):
    value = json.loads(command('/usr/bin/python3', '-I', '-B', '/usr/libexec/elderbrain-recovery.py', phase))
    assert value['state'] == 'no-update-recovery-needed', value
command('systemctl', 'daemon-reload')
assert persistent_identity(state, Path('/')) == identity
print(json.dumps({'state': 'bootstrap-installed-and-verified', 'bundle': result['bundle'],
                  'history': result['history'], 'activationReady': False}), flush=True)
