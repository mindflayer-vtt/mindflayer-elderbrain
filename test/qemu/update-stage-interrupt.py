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
parser.add_argument('stage', choices=('downloading-host', 'downloading-dependencies',
                                      'preparing-runtime', 'preparing-recovery',
                                      'committing-recovery'))
parser.add_argument('--version')
parser.add_argument('--manifest')
args = parser.parse_args()
if args.job != 'next' and not re.fullmatch(r'[a-f0-9]{32}', args.job):
    raise ValueError('Invalid disposable job identity')
if args.job == 'next':
    if (not isinstance(args.version, str)
            or not re.fullmatch(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)', args.version)
            or not isinstance(args.manifest, str) or not re.fullmatch(r'[a-f0-9]{64}', args.manifest)):
        raise ValueError('Next-job mode requires an exact version and manifest digest')
elif args.version is not None or args.manifest is not None:
    raise ValueError('Exact job mode does not accept release discovery fields')
assert os.geteuid() == 0
assert Path('/sys/class/dmi/id/product_name').read_text().startswith('Standard PC')
assert subprocess.check_output(['lsblk', '-dn', '-o', 'SERIAL', '/dev/vda'], text=True).strip() == 'elderbrain-vm-test'

jobs = Path('/var/lib/mindflayer-elderbrain/jobs')
deadline = time.monotonic() + 300
job = args.job
if job == 'next':
    existing = {path.stem for path in jobs.glob('*.json')}
    print('Waiting for exact next update job', flush=True)
    while time.monotonic() < deadline:
        matches = []
        for candidate in jobs.glob('*.json'):
            if candidate.stem in existing or not re.fullmatch(r'[a-f0-9]{32}', candidate.stem):
                continue
            try:
                record = json.loads(candidate.read_text())
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if (record.get('id') == candidate.stem and record.get('kind') == 'update'
                    and record.get('state') in ('queued', 'running')
                    and record.get('request', {}).get('version') == args.version
                    and record.get('request', {}).get('manifestSha256') == args.manifest):
                matches.append(candidate.stem)
        if len(matches) > 1:
            raise RuntimeError('Multiple matching update jobs appeared')
        if matches:
            job = matches[0]
            break
        time.sleep(0.01)
    else:
        raise TimeoutError('Exact next update job did not appear')
path, lock = jobs / (job + '.json'), jobs / (job + '.lock')
while time.monotonic() < deadline:
    record = json.loads(path.read_text())
    if record.get('kind') != 'update' or record.get('id') != job:
        raise ValueError('Refusing an unrelated job')
    if record.get('state') not in ('queued', 'running'):
        raise RuntimeError('Update became terminal before the requested stage')
    if record.get('stage') == args.stage:
        before = os.readlink('/usr/lib/elderbrain-recovery/bootstrap-active')
        subprocess.run(['systemctl', 'kill', '--kill-whom=all', '--signal=KILL',
                        'elderbrain-job-' + job + '.scope'], check=True,
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
            'job': job, 'stage': args.stage, 'bootId': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'selectorBefore': before, 'selectorAfter': os.readlink('/usr/lib/elderbrain-recovery/bootstrap-active'),
            'jobState': current.get('state'), 'jobStage': current.get('stage'),
            'maintenanceId': maintenance.get('id'), 'maintenanceState': maintenance.get('state'),
        })
        print(evidence, flush=True)
        raise SystemExit(0)
    time.sleep(0.01)
raise TimeoutError('Update did not reach the requested interruption stage')
