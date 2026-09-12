#!/usr/bin/env python3
"""Kill one identified disposable-VM update worker at a durable stage boundary."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'appliance/lib'))
from backup_service import save_record

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('job')
parser.add_argument('stage', choices=('committing-recovery',))
args = parser.parse_args()
if not re.fullmatch(r'[a-f0-9]{32}', args.job):
    raise ValueError('Invalid disposable job identity')
assert os.geteuid() == 0
assert Path('/sys/class/dmi/id/product_name').read_text().startswith('Standard PC')
assert subprocess.check_output(['lsblk', '-dn', '-o', 'SERIAL', '/dev/vda'], text=True).strip() == 'elderbrain-vm-test'

jobs = Path('/var/lib/mindflayer-elderbrain/jobs')
path, lock = jobs / (args.job + '.json'), jobs / (args.job + '.lock')
deadline = time.monotonic() + 300
while time.monotonic() < deadline:
    record = json.loads(path.read_text())
    if record.get('kind') != 'update' or record.get('id') != args.job:
        raise ValueError('Refusing an unrelated job')
    if record.get('state') not in ('queued', 'running'):
        raise RuntimeError('Update became terminal before the requested stage')
    if record.get('stage') == args.stage:
        before = os.readlink('/usr/lib/elderbrain-recovery/bootstrap-active')
        subprocess.run(['systemctl', 'kill', '--kill-whom=all', '--signal=KILL',
                        'elderbrain-job-' + args.job + '.scope'], check=True,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=15)
        descriptor = os.open(lock, os.O_RDWR | os.O_NOFOLLOW)
        try:
            for _ in range(200):
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(0.01)
            else:
                raise RuntimeError('Interrupted worker retained its lock')
        finally:
            os.close(descriptor)
        evidence = Path(tempfile.mkdtemp(prefix='elderbrain-update-stage-interrupt-', dir='/root'))
        maintenance = json.loads(Path('/var/lib/mindflayer-elderbrain/maintenance/maintenance.json').read_text())
        current = json.loads(path.read_text())
        save_record(evidence / 'interruption.json', {
            'job': args.job, 'stage': args.stage, 'bootId': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'selectorBefore': before, 'selectorAfter': os.readlink('/usr/lib/elderbrain-recovery/bootstrap-active'),
            'jobState': current.get('state'), 'jobStage': current.get('stage'),
            'maintenanceId': maintenance.get('id'), 'maintenanceState': maintenance.get('state'),
        })
        print(evidence, flush=True)
        raise SystemExit(0)
    time.sleep(0.01)
raise TimeoutError('Update did not reach the requested interruption stage')
