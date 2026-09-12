"""Inject process loss after a real VM file rename, then verify boot rollback."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'appliance/lib'))
from backup_service import Maintenance, save_record
from provisioning.recovery_bootstrap import provision, staged_payload
from release_baseline import prepare
from release_baseline_install import Migration
from release_bootstrap import verify_installed
from release_recovery import health
from release_services import UpdateServices


def command(*args):
    return subprocess.check_output(args, text=True, timeout=60).strip()


def fingerprint(path):
    return {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'inode': path.stat().st_ino}


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('phase', choices=('interrupt', 'verify'))
parser.add_argument('--evidence', type=Path)
args = parser.parse_args()
assert os.geteuid() == 0
assert Path('/sys/class/dmi/id/product_name').read_text().startswith('Standard PC')
assert command('lsblk', '-dn', '-o', 'SERIAL', '/dev/vda') == 'elderbrain-vm-test'
state, runtime = Path('/var/lib/mindflayer-elderbrain'), Path('/opt/mindflayer-elderbrain')
compose = runtime / 'compose.yaml'
stack = Path('/etc/systemd/system/elderbrain-stack.service')
services = UpdateServices(runtime, health_check=lambda saved: health(saved, state))
maintenance = Maintenance(state / 'maintenance', services)

if args.phase == 'interrupt':
    assert args.evidence is None
    provision()
    command('systemctl', 'daemon-reload')
    directory = Path(tempfile.mkdtemp(prefix='elderbrain-interrupted-baseline-', dir='/root'))
    prepared = prepare(runtime, state=state, directory=directory)
    evidence = {'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                'compose': fingerprint(compose), 'stack': fingerprint(stack)}
    save_record(directory / 'evidence.json', evidence)
    rename = os.rename
    def interrupted(source, destination):
        rename(source, destination)
        if Path(source) == compose:
            raise SystemExit('injected process loss after moving original Compose')
    with staged_payload() as (tree, paths):
        try:
            with patch('restore_transaction.os.rename', side_effect=interrupted):
                Migration(maintenance).install(Path(prepared['directory']), ROOT / 'release/elderbrain-stack.service',
                    require_bootstrap=lambda: verify_installed(tree, paths), run=subprocess.run)
        except SystemExit as error:
            assert str(error) == 'injected process loss after moving original Compose'
        else:
            raise AssertionError('Expected migration interruption')
    assert not compose.exists(), 'Original Compose should be retained privately, not live'
    assert fingerprint(stack) == evidence['stack']
    record = maintenance.previous()
    assert record['operation'] == 'baseline' and record['state'] == 'installing'
    evidence['migration'] = record['id']
    save_record(directory / 'evidence.json', evidence)
    print(json.dumps({'state': 'interrupted-before-reboot', 'id': record['id'],
                      'evidence': str(directory / 'evidence.json')}), flush=True)
else:
    assert args.evidence is not None
    evidence = json.loads(args.evidence.read_text())
    assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() != evidence['boot']
    assert fingerprint(compose) == evidence['compose']
    assert fingerprint(stack) == evidence['stack']
    record = maintenance.previous()
    assert record['id'] == evidence['migration'] and record['state'] == 'rolled-back'
    times = {}
    for unit in ('elderbrain-update-recovery', 'elderbrain-stack', 'elderbrain-graphics', 'elderbrain-update-finish'):
        assert command('systemctl', 'is-active', unit) == 'active'
        times[unit] = int(command('systemctl', 'show', unit, '--value', '--property=ActiveEnterTimestampMonotonic'))
    assert times['elderbrain-update-recovery'] < times['elderbrain-stack'] <= times['elderbrain-update-finish']
    services.validate()
    health(services.snapshot(), state)
    print(json.dumps({'state': 'interrupted-baseline-boot-rollback-passed', 'id': record['id'],
                      'activationTimesMicroseconds': times}), flush=True)
