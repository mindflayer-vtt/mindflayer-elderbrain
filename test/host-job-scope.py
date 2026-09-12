"""Verify scope survival and inherited FDs using disposable user systemd units.

Run as the logged-in developer, outside the socket-restricted sandbox. This does
not exercise root appliance services; that qualification belongs in the VM.
"""
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid


def wait_for(path):
    deadline = time.monotonic() + 20
    while not path.exists():
        if time.monotonic() > deadline:
            raise RuntimeError('Scope fixture timed out: ' + path.name)
        time.sleep(0.05)


def child(root, lock, secret):
    assert os.read(secret, 100) == b'non-secret-fixture'
    cgroup = Path('/proc/self/cgroup').read_text()
    assert 'elderbrain-job-scope-fixture-' in cgroup and '.scope' in cgroup
    (root / 'ready').touch()
    wait_for(root / 'continue')
    os.fstat(lock)
    (root / 'completed').touch()


def parent(root, unit):
    lock = os.open(root / 'lock', os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX)
    secret = os.memfd_create('scope-fixture', os.MFD_CLOEXEC)
    os.write(secret, b'non-secret-fixture')
    os.lseek(secret, 0, 0)
    process = subprocess.Popen(['systemd-run', '--user', '--scope', '--quiet', '--collect',
                                '--unit=' + unit, '--expand-environment=no', '--',
                                sys.executable, str(Path(__file__).resolve()), 'child', str(root), str(lock), str(secret)],
                               pass_fds=(lock, secret), start_new_session=True,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    process.wait()


def verify():
    unit = 'elderbrain-job-scope-fixture-' + uuid.uuid4().hex
    launcher = unit + '-launcher'
    with tempfile.TemporaryDirectory(prefix='elderbrain-job-scope-') as directory:
        root = Path(directory)
        try:
            subprocess.run(['systemd-run', '--user', '--quiet', '--collect', '--unit=' + launcher,
                            '--', sys.executable, str(Path(__file__).resolve()), 'parent', str(root), unit],
                           check=True, timeout=15)
            wait_for(root / 'ready')
            subprocess.run(['systemctl', '--user', 'stop', launcher + '.service'], check=True, timeout=15)
            with open(root / 'lock', 'r') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    pass
                else:
                    raise AssertionError('Worker lost its lock after launcher stopped')
            (root / 'continue').touch()
            wait_for(root / 'completed')
            print('PASS: worker scope survives launcher stop and retains lock and memory-only input')
        finally:
            # Only these uniquely named disposable fixture units are in scope.
            subprocess.run(['systemctl', '--user', 'stop', launcher + '.service', unit + '.scope'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)


if __name__ == '__main__':
    if len(sys.argv) == 1:
        verify()
    elif sys.argv[1] == 'parent':
        parent(Path(sys.argv[2]), sys.argv[3])
    elif sys.argv[1] == 'child':
        child(Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]))
