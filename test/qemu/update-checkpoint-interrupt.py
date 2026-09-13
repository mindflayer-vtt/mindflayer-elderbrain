#!/usr/bin/env python3
"""Kill one exact disposable update after Btrfs capture but before publication."""
import argparse
import ctypes
import fcntl
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'appliance/lib'))
from backup_service import save_record


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('job')
parser.add_argument('version')
parser.add_argument('manifest')
args = parser.parse_args()
if (not re.fullmatch(r'[a-f0-9]{32}', args.job)
        or not re.fullmatch(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)', args.version)
        or not re.fullmatch(r'[a-f0-9]{64}', args.manifest)):
    raise ValueError('An exact job, version and manifest digest are required')
assert os.geteuid() == 0
assert Path('/sys/class/dmi/id/product_name').read_text().startswith('Standard PC')
assert subprocess.check_output(['lsblk', '-dn', '-o', 'SERIAL', '/dev/vda'], text=True).strip() == 'elderbrain-vm-test'

state = Path('/var/lib/mindflayer-elderbrain')
jobs, snapshots = state / 'jobs', state / 'snapshots'
snapshots.mkdir(mode=0o700, exist_ok=True)
deadline = time.monotonic() + 300
while time.monotonic() < deadline:
    try:
        job = json.loads((jobs / (args.job + '.json')).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        time.sleep(0.01)
        continue
    if (job.get('id') == args.job and job.get('kind') == 'update'
            and job.get('state') in ('queued', 'running')
            and job.get('request', {}).get('version') == args.version
            and job.get('request', {}).get('manifestSha256') == args.manifest):
        break
    raise RuntimeError('Exact update job does not match the requested release')
else:
    raise TimeoutError('Exact update job did not appear')

libc = ctypes.CDLL(None, use_errno=True)
libc.inotify_add_watch.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32)
descriptor = libc.inotify_init1(os.O_CLOEXEC)
if descriptor < 0:
    error = ctypes.get_errno()
    raise OSError(error, os.strerror(error))
try:
    if libc.inotify_add_watch(descriptor, os.fsencode(snapshots), 0x100) < 0:  # IN_CREATE
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    checkpoint = None
    while time.monotonic() < deadline:
        ready, _, _ = __import__('select').select([descriptor], [], [], max(0, deadline - time.monotonic()))
        if not ready:
            break
        events = os.read(descriptor, 4096)
        offset = 0
        while offset < len(events):
            _, mask, _, length = struct.unpack_from('iIII', events, offset)
            name = events[offset + 16:offset + 16 + length].split(b'\0', 1)[0].decode()
            offset += 16 + length
            if mask & 0x100 and re.fullmatch(r'[a-f0-9]{32}', name):
                checkpoint = name
                break
        if checkpoint is not None:
            break
    if checkpoint is None:
        raise TimeoutError('Update checkpoint subvolume was not created')
finally:
    os.close(descriptor)

maintenance = json.loads((state / 'maintenance/maintenance.json').read_text())
if (maintenance.get('operation') != 'update' or maintenance.get('jobId') != args.job
        or maintenance.get('version') != args.version or maintenance.get('manifestSha256') != args.manifest
        or maintenance.get('state') != 'checkpointing' or 'rollbackCheckpoint' in maintenance):
    raise RuntimeError('Checkpoint event did not belong to the exact unpublished update checkpoint')
subprocess.run(['systemctl', 'kill', '--kill-whom=all', '--signal=KILL',
                'elderbrain-job-' + args.job + '.scope'], check=True,
               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
               stderr=subprocess.DEVNULL, timeout=15)
lock = os.open(jobs / (args.job + '.lock'), os.O_RDWR | os.O_NOFOLLOW)
try:
    for _ in range(200):
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            time.sleep(0.01)
    else:
        raise RuntimeError('Interrupted worker retained its lock')
finally:
    os.close(lock)

destination = snapshots / checkpoint
if (not destination.is_dir() or destination.stat().st_ino != 256
        or (snapshots / (checkpoint + '.json')).exists()
        or list(snapshots.glob(checkpoint + '.*.pin'))):
    raise RuntimeError('Checkpoint was not interrupted between capture and publication')
evidence = Path(tempfile.mkdtemp(prefix='elderbrain-update-checkpoint-interrupt-', dir='/root'))
save_record(evidence / 'interruption.json', {
    'job': args.job, 'bootId': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
    'maintenanceId': maintenance['id'], 'maintenanceState': maintenance['state'],
    'checkpoint': checkpoint, 'snapshotExists': True, 'metadataExists': False,
    'pinExists': False, 'rollbackCheckpointPublished': False,
})
print(evidence, flush=True)
