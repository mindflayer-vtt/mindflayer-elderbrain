"""Verify real boot-time code/data recovery after the signed update fixture."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'appliance/lib'))
from release_recovery import health
from release_services import UpdateServices


def command(*args):
    return subprocess.check_output(args, text=True, timeout=60).strip()


assert os.geteuid() == 0
assert Path('/sys/class/dmi/id/product_name').read_text().startswith('Standard PC')
assert command('lsblk', '-dn', '-o', 'SERIAL', '/dev/vda') == 'elderbrain-vm-test'
evidence = json.loads(Path(sys.argv[1]).read_text())
state, runtime = Path('/var/lib/mindflayer-elderbrain'), Path('/opt/mindflayer-elderbrain')
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() != evidence['boot']
assert (runtime / 'VERSION').read_text() == evidence['version']
assert hashlib.sha256((runtime / 'compose.yaml').read_bytes()).hexdigest() == evidence['composeSha256']
marker = Path(evidence['marker'])
assert marker.parent == state / 'foundry' and marker.name.startswith('.elderbrain-rollback-test-')
assert marker.read_bytes() == b'before-update\n'
record = json.loads((state / 'maintenance/maintenance.json').read_text())
assert record['id'] == evidence['id'] and record['state'] == 'rolled-back' and record['dataRolledBack'] is True
assert not (state / 'snapshots' / (record['rollbackCheckpoint'] + '.' + record['id'] + '.pin')).exists()
times = {}
for unit in ('elderbrain-update-recovery', 'docker', 'elderbrain-management', 'elderbrain-stack',
             'elderbrain-graphics', 'elderbrain-update-finish'):
    assert command('systemctl', 'is-active', unit) == 'active'
    times[unit] = int(command('systemctl', 'show', unit, '--value', '--property=ActiveEnterTimestampMonotonic'))
assert times['elderbrain-update-recovery'] < times['docker'] <= times['elderbrain-stack'] <= times['elderbrain-update-finish']
services = UpdateServices(runtime, health_check=lambda saved: health(saved, state))
services.validate()
health(services.snapshot(), state)
print(json.dumps({'state': 'signed-update-boot-code-data-recovery-passed', 'id': record['id'],
                  'activationTimesMicroseconds': times}), flush=True)
