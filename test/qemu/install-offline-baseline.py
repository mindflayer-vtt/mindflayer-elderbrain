"""Migrate only the explicitly identified disposable VM to offline stack startup."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'appliance/lib'))
from backup_service import Maintenance
from provisioning.recovery_bootstrap import provision, staged_payload
from release_baseline import prepare
from release_baseline_install import Migration
from release_bootstrap import verify_installed, WRITERS
from release_recovery import health
from release_services import UpdateServices


def command(*args):
    return subprocess.check_output(args, text=True, timeout=60).strip()


assert os.geteuid() == 0
assert Path('/sys/class/dmi/id/product_name').read_text().startswith('Standard PC')
assert command('lsblk', '-dn', '-o', 'SERIAL', '/dev/vda') == 'elderbrain-vm-test'
state, runtime = Path('/var/lib/mindflayer-elderbrain'), Path('/opt/mindflayer-elderbrain')
provision()  # Publish this exact migration recovery code before changing runtime.
command('systemctl', 'daemon-reload')
directory = Path(tempfile.mkdtemp(prefix='elderbrain-baseline-migration-', dir='/root'))
prepared = prepare(runtime, state=state, directory=directory)
services = UpdateServices(runtime, health_check=lambda saved: health(saved, state))
maintenance = Maintenance(state / 'maintenance', services)
with staged_payload() as (tree, paths):
    def prerequisite():
        verify_installed(tree, paths)
        for unit in WRITERS:
            for relationship in ('Requires', 'After'):
                assert 'elderbrain-update-recovery.service' in command(
                    'systemctl', 'show', unit, '--property=' + relationship, '--value').split(), (unit, relationship)
    result = Migration(maintenance).install(Path(prepared['directory']), ROOT / 'release/elderbrain-stack.service',
                                          require_bootstrap=prerequisite, run=subprocess.run)
assert result['state'] == 'completed' and result['activationReady'] is False
print(json.dumps({'state': 'offline-baseline-installed', 'id': result['id'],
                  'prepared': prepared['directory'], 'activationReady': False}), flush=True)
