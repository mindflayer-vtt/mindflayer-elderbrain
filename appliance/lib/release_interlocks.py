"""Host admission locks shared by update workers and interactive settings."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path

from backup_service import Maintenance
from host_jobs import ACTIVE, JobStore


@contextmanager
def update_admission(state, *, owner=None):
    """Hold outside maintenance; exclude queued jobs as well as running workers.

An admitted update worker may supply its own job ID. No PID or stale JSON record
is accepted as liveness: JobStore checks the worker-held lock.
"""
    jobs = JobStore(Path(state) / 'jobs')
    descriptor = os.open(jobs.directory / 'admission.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('Host job admission is in progress') from error
        active = [record for record in jobs.list() if record['state'] in ACTIVE]
        if owner is not None:
            jobs.path(owner)  # Validate the identifier before comparing it.
            own = [record for record in active if record['id'] == owner and record.get('kind') == 'update']
            if len(own) != 1:
                raise ValueError('Update worker must own a live admitted update job')
        if any(record['id'] != owner for record in active):
            raise RuntimeError('Another host job is running')
        yield
    finally:
        os.close(descriptor)


@contextmanager
def settings_admission(state):
    """Lock order is maintenance then display/network transaction lock."""
    maintenance = Maintenance(Path(state) / 'maintenance', None)
    with maintenance.locked():
        if maintenance.previous().get('state') not in (None, 'completed', 'failed', 'recovered', 'rolled-back'):
            raise RuntimeError('Recover maintenance before changing appliance settings')
        yield
