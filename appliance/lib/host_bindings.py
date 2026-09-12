"""Refresh fixed persistent host aliases after journaled directory replacement."""

import json
from pathlib import Path
import re
import subprocess

ALIASES = {'ssh-server': 'etc/ssh', 'ssh-root': 'root/.ssh',
           'ssh-admin': 'home/elderbrain-installer/.ssh', 'netplan': 'etc/netplan'}


def refresh(state, data_uuid, names, *, host_root=Path('/'), run=subprocess.run):
    """Caller holds maintenance lock, has verified storage and stopped writers.

    Never lazily unmount or stack mounts. Interrupted refresh is retryable:
    an absent alias is mounted directly; an unexpected mounted source aborts.
    """
    if not set(names) <= set(ALIASES):
        raise ValueError('Unknown persistent host alias')
    state, host_root = Path(state), Path(host_root)
    for name in sorted(names):
        source = state / 'host' / name
        target = host_root / ALIASES[name]
        if (source.resolve() != source or target.resolve() != target
                or not source.is_dir() or not target.is_dir()):
            raise ValueError('Persistent alias requires real, existing directories')
        result = run(['findmnt', '--json', '--mountpoint', str(target), '--output',
                      'TARGET,FSTYPE,UUID,FSROOT'], check=False, capture_output=True,
                     text=True, timeout=20)
        if result.returncode == 0:
            mounts = json.loads(result.stdout).get('filesystems')
            if not isinstance(mounts, list) or len(mounts) != 1:
                raise ValueError('Ambiguous persistent host alias mount')
            mount = mounts[0]
            previous = rf'/host/\.elderbrain-restore-[a-f0-9]{{32}}-{re.escape(name)}/(?:previous|rejected)'
            if (mount.get('target') != str(target) or mount.get('fstype') != 'btrfs'
                    or mount.get('uuid') != data_uuid
                    or not (mount.get('fsroot') == '/host/' + name
                            or re.fullmatch(previous, mount.get('fsroot', '')))):
                raise ValueError('Refusing to replace an unexpected host alias mount')
            run(['umount', str(target)], check=True, capture_output=True,
                text=True, timeout=20)
        elif result.returncode != 1:
            raise RuntimeError('Unable to inspect persistent host alias mount')
        run(['mount', '--bind', str(source), str(target)], check=True,
            capture_output=True, text=True, timeout=20)
        # Check the actual inode, not just the UUID: the old and new directory
        # trees are intentionally on the same filesystem during a restore.
        if not source.samefile(target):
            raise RuntimeError('Persistent host alias does not expose the restored tree')
