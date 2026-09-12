"""Persistent host-directory preparation for fresh and preserve installs.

Bind mounts keep atomic file replacement working at the original OS paths.
Do not use single-file binds for settings written with rename(2).
Caller must verify the data mount first and run before host services start.
"""

import os
from pathlib import Path
import stat
import subprocess
import tempfile
import argparse
import json

STATE = '/var/lib/mindflayer-elderbrain'
# The whole SSH directory is already a supported backup/restore root. Keeping
# it retains host identity and administrator-configured SSH policy as well.
DIRECTORIES = {
    'netplan': '/etc/netplan',
    'ssh-server': '/etc/ssh',
    'ssh-root': '/root/.ssh',
    'ssh-admin': '/home/elderbrain-installer/.ssh',
}


def directory(path):
    info = Path(path).lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError('Persistent host configuration must be a real directory')


def seed(name, *, mode, os_root='/', state_root=STATE, run=subprocess.run):
    if name not in DIRECTORIES or mode not in ('fresh', 'preserve'):
        raise ValueError('Unsupported host directory or installation mode')
    source = Path(os_root) / DIRECTORIES[name].lstrip('/')
    parent = Path(state_root) / 'host'
    destination = parent / name
    directory(state_root)
    if mode == 'preserve':
        # Missing preserved config is an error, never a reason to seed new OS
        # defaults over user state or silently regenerate SSH identity.
        directory(parent)
        directory(destination)
        return destination
    if destination.exists() or destination.is_symlink():
        raise ValueError('Fresh host configuration destination already exists')
    directory(source)
    parent.mkdir(mode=0o700, exist_ok=True)
    directory(parent)
    staging = Path(tempfile.mkdtemp(prefix=f'.{name}-seed-', dir=parent))
    # Do not recursively clean up on failure: retain partial seed for diagnosis.
    # It is never accepted as the canonical directory.
    run(['cp', '-a', '--', str(source) + '/.', str(staging)],
        check=True, capture_output=True, text=True, timeout=60)
    run(['sync', '-f', str(staging)], check=True, capture_output=True,
        text=True, timeout=60)
    os.rename(staging, destination)
    fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return destination


def fstab_entries():
    return ''.join(
        f'{STATE}/host/{name} {target} none '
        f'bind,x-systemd.requires-mounts-for={STATE} 0 0\n'
        for name, target in DIRECTORIES.items())


def merge_fstab(original):
    """Idempotently append only our fixed directory mounts; reject conflicts."""
    desired = fstab_entries().splitlines()
    targets = set(DIRECTORIES.values())
    present = set()
    for line in original.splitlines():
        fields = line.split('#', 1)[0].split()
        if len(fields) >= 2 and fields[1] in targets:
            canonical = ' '.join(fields)
            if canonical not in desired or fields[1] in present:
                raise ValueError('Existing fstab conflicts with persistent host configuration')
            present.add(fields[1])
    suffix = [line for line in desired if line.split()[1] not in present]
    if not suffix:
        return original
    return original.rstrip('\n') + '\n' + '\n'.join(suffix) + '\n'


def activate(*, mode, os_root='/', state_root=STATE, identity,
             run=subprocess.run, write=None, bind=None):
    """Seed or validate all directories before publishing mounts.

    Intended for the installer's stopped target. Callers must verify persistent
    storage first; live remapping of unrelated mounts is never permitted.
    """
    from iso.storage_select import atomic_write
    from appliance.lib.host_bindings import refresh
    write = write or atomic_write
    bind = bind or refresh
    os_root, state_root = Path(os_root), Path(state_root)
    fstab = os_root / 'etc/fstab'
    if fstab.is_symlink():
        raise ValueError('Refusing symlink fstab')
    updated = merge_fstab(fstab.read_text())  # reject conflicts before seeding
    for name, target in DIRECTORIES.items():
        path = os_root / target.lstrip('/')
        if not path.exists() and not path.is_symlink():
            # Missing SSH key directories are normal on a fresh OS. These are
            # only mountpoints in preserve mode, never sources for replacement.
            path.mkdir(mode=0o700, parents=True)
        directory(path)
        seed(name, mode=mode, os_root=os_root, state_root=state_root, run=run)
    write(fstab, updated)
    for name, target in DIRECTORIES.items():
        source = state_root / 'host' / name
        alias = os_root / target.lstrip('/')
        if not source.samefile(alias):
            bind(state_root, identity['data_uuid'], [name], host_root=os_root, run=run)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt')
    args = parser.parse_args()
    from appliance.lib.storage_guard import check, read_identity
    check()
    mode = 'preserve'
    if args.receipt:
        mode = json.loads(Path(args.receipt).read_text())['mode']
    activate(mode=mode, identity=read_identity('/etc/elderbrain/storage.json'))


if __name__ == '__main__':
    main()
