"""Run as root in a private mount namespace on a disposable VM.

Creates/formats only a new, exclusively created 256 MiB regular file. Leaves
the image and journals for diagnosis; unmounts only the two test mountpoints.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from host_bindings import refresh
from restore_transaction import RestoreTransaction


def run(*arguments):
    return subprocess.run(arguments, check=True, capture_output=True, text=True, timeout=30)


def main():
    if os.geteuid() != 0:
        raise SystemExit('Requires root in a disposable VM/private mount namespace')
    root = Path(tempfile.mkdtemp(prefix='elderbrain-storage-bindings-', dir='/tmp'))
    disk = root / 'test.btrfs'
    with disk.open('xb') as stream:
        stream.truncate(256 * 1024**2)
    run('mkfs.btrfs', str(disk))
    state = root / 'data'
    target = root / 'root/.ssh'
    state.mkdir()
    target.mkdir(parents=True)
    mounted = False
    try:
        run('mount', '-t', 'btrfs', '-o', 'loop', str(disk), str(state))
        mounted = True
        uuid = run('findmnt', '-n', '-o', 'UUID', '--mountpoint', str(state)).stdout.strip()
        source = state / 'host/ssh-root'
        source.mkdir(parents=True)
        (source / 'fixture').write_text('old')
        incoming = root / 'incoming'
        incoming.mkdir()
        (incoming / 'fixture').write_text('new')
        run('mount', '--bind', str(source), str(target))
        transaction = RestoreTransaction(root / 'journal.json', {'ssh-root': source})
        transaction.prepare({'ssh-root': incoming})
        transaction.apply()
        assert (target / 'fixture').read_text() == 'old', 'Expected old bind inode before refresh'
        refresh(state, uuid, ['ssh-root'], host_root=root)
        assert (target / 'fixture').read_text() == 'new'
        transaction.rollback()
        assert (target / 'fixture').read_text() == 'new', 'Expected rejected bind inode before refresh'
        refresh(state, uuid, ['ssh-root'], host_root=root)
        assert (target / 'fixture').read_text() == 'old'
        # Simulate interruption after normal unmount, before the new bind.
        run('umount', str(target))
        refresh(state, uuid, ['ssh-root'], host_root=root)
        assert (target / 'fixture').read_text() == 'old'
        print(json.dumps({'result': 'passed', 'artifacts': str(root),
                          'checks': ['apply-refresh', 'rollback-refresh', 'missing-alias-recovery']}))
    finally:
        # No recursive cleanup, forced unmounts, or broad device operations.
        if subprocess.run(['findmnt', '--mountpoint', str(target)], capture_output=True).returncode == 0:
            run('umount', str(target))
        if mounted:
            run('umount', str(state))


if __name__ == '__main__':
    main()
