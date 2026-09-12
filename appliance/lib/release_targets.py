"""Trusted host deployment map. Release metadata never chooses destination paths."""
from pathlib import Path
import os
import stat


SERVICES = ('elderbrain-admin-console', 'elderbrain-backup', 'elderbrain-display-watchdog',
            'elderbrain-graphics', 'elderbrain-management', 'elderbrain-network-confirmation',
            'elderbrain-network-recovery', 'elderbrain-network-watchdog', 'elderbrain-stack',
            'elderbrain-storage')
STORAGE_WRITERS = ('docker', *(name for name in SERVICES if name != 'elderbrain-storage'))


def bindings():
    """Destination-relative path -> authenticated candidate-relative source."""
    result = {'opt/mindflayer-elderbrain': 'runtime', 'usr/local/sbin/elderbrain': 'bin/elderbrain',
              'etc/opt/chrome/policies/managed/elderbrain.json': 'templates/chrome/elderbrain.json',
              'etc/cloud/cloud.cfg.d/99-elderbrain-ssh-identity.cfg': 'templates/cloud/99-elderbrain-ssh-identity.cfg'}
    for name in SERVICES:
        result['etc/systemd/system/' + name + '.service'] = 'units/' + name + '.service'
    for name in STORAGE_WRITERS:
        result['etc/systemd/system/' + name + '.service.d/10-storage-required.conf'] = 'units/storage-required.conf'
    for name in ('systemd-networkd', 'NetworkManager'):
        result['etc/systemd/system/' + name + '.service.d/elderbrain-recovery.conf'] = 'units/network-recovery.conf'
    result['etc/systemd/system/elderbrain-network-recovery.service.d/20-persistent-netplan.conf'] = 'units/persistent-netplan.conf'
    return result


def targets(host_root=Path('/')):
    """Same map is used during activation and recovery, independent of archives."""
    host_root = Path(host_root).absolute()
    if host_root.resolve() != host_root or not host_root.is_dir():
        raise ValueError('Deployment root must be a canonical directory')
    return {name: host_root / name for name in bindings()}


def sources(tree, host_root=Path('/')):
    """Preflight only: no target directories/files or missing defaults are created.

Caller must retain the signed candidate context through transaction preparation.
The runtime includes only reconstructed code plus verified persistent aliases.
Individual managed drop-ins are replaced; user-created sibling overrides survive.
"""
    tree = Path(tree).absolute()
    if tree.resolve() != tree or not tree.is_dir():
        raise ValueError('Deployment candidate must be a canonical directory')
    destinations = targets(host_root)
    selected = {}
    for name, relative in bindings().items():
        source, target = tree / relative, destinations[name]
        info = source.lstat()
        valid_type = stat.S_ISDIR(info.st_mode) if relative == 'runtime' else stat.S_ISREG(info.st_mode)
        if not valid_type or source.resolve() != source or info.st_uid != os.geteuid() or info.st_mode & 0o7022:
            raise ValueError('Invalid managed deployment source')
        if target.resolve() != target or not target.parent.is_dir() or target.is_mount():
            raise ValueError('Managed deployment target is missing, aliased or mounted')
        root = Path(host_root).absolute()
        for parent in target.parents:
            info = parent.lstat()
            if info.st_uid != os.geteuid() or info.st_mode & 0o022:
                raise ValueError('Managed deployment target parent is writable by another account')
            if parent == root:
                break
        if target.exists():
            mode = target.lstat().st_mode
            if not (stat.S_ISDIR(mode) if relative == 'runtime' else stat.S_ISREG(mode)):
                raise ValueError('Unexpected managed deployment target type')
        selected[name] = source
    return selected
