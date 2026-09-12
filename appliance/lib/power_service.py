"""Power admission: no active jobs, maintenance or pending display/network edits."""
import fcntl
import json
import os
from pathlib import Path
import subprocess

from backup_service import Maintenance, save_record


def pending(state):
    path = Path(state) / 'power.json'
    if not path.exists():
        return False
    value = json.loads(path.read_text())
    return value.get('state') == 'requested' and value.get('bootId') == Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def request(value):
    if (not isinstance(value, dict) or set(value) != {'action', 'confirmPower'}
            or value['action'] not in ('reboot', 'shutdown') or value['confirmPower'] is not True):
        raise ValueError('Power request requires an allowed action and explicit confirmation')
    return dict(value)


def run_job(state, identity, selected, *, host_root=Path('/')):
    selected = request(selected)
    if Path(state).absolute() != Path(host_root).absolute() / 'var/lib/mindflayer-elderbrain':
        raise ValueError('Power worker requires the fixed appliance state directory')
    return operate(selected['action'], owner=identity, host_root=host_root)


def operate(action, *, host_root=Path('/'), run=subprocess.run, owner=None):
    from host_jobs import JobStore, ACTIVE
    from restore_service import persistent_identity
    from snapshot_service import stable_settings
    if action not in ('reboot', 'shutdown'):
        raise ValueError('Unsupported power action')
    root = Path(host_root).absolute()
    state = root / 'var/lib/mindflayer-elderbrain'
    if persistent_identity(state, root) is None:
        raise ValueError('Power controls require verified persistent storage')
    jobs = JobStore(state / 'jobs')
    descriptor = os.open(jobs.directory / 'admission.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('Host job admission is in progress') from error
        active = [job for job in jobs.list() if job['state'] in ACTIVE]
        if owner is not None:
            jobs.path(owner)
            own = [job for job in active if job['id'] == owner and job.get('kind') == 'power'
                   and job.get('request') == {'action': action, 'confirmPower': True}]
            if len(own) != 1:
                raise ValueError('Power worker must own the matching live confirmed job')
        if pending(state) or any(job['id'] != owner for job in active):
            raise RuntimeError('A host job or power operation is active')
        maintenance = Maintenance(state / 'maintenance', None)
        with maintenance.locked(), stable_settings(state):
            if maintenance.previous().get('state') not in (None, 'completed', 'failed', 'recovered', 'rolled-back'):
                raise RuntimeError('Recover interrupted maintenance before changing power state')
            record = {'state': 'requested', 'action': action,
                      'bootId': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
            if owner is not None:
                record['jobId'] = owner
            save_record(state / 'power.json', record)
            try:
                run(['systemctl', '--no-block', 'reboot' if action == 'reboot' else 'poweroff'], check=True,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
            except Exception:
                save_record(state / 'power.json', {**record, 'state': 'failed'})
                raise
            return record
    finally:
        os.close(descriptor)


if __name__ == '__main__':
    import sys
    if os.geteuid() != 0 or len(sys.argv) != 2:
        raise SystemExit('Power controls require root and one action')
    print(json.dumps(operate(sys.argv[1])))
