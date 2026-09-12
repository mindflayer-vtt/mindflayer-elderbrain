"""Install fixed recovery boot prerequisites from a caller-authenticated tree.

This does not authenticate archives, activate a release, or start services.
Bootstrap completion is not update readiness: migration and qualification of the
previous runtime are still required before admitting an update.
"""
import os
import hashlib
import json
from pathlib import Path
import stat
import tempfile
import uuid

from backup_service import Maintenance, save_record
from release_interlocks import update_admission
from release_prepare import sync_directory
from release_recovery_bundle import install as install_bundle, selection_window, verify_tree
from release_runtime import private_directory, read_regular
from release_staging import inventory
from restore_service import persistent_identity

WRITERS = ('docker.service', 'docker.socket', 'containerd.service', 'elderbrain-stack.service',
           'elderbrain-graphics.service', 'elderbrain-backup.service', 'elderbrain-management.service',
           'elderbrain-display-watchdog.service', 'elderbrain-network-watchdog.service',
           'elderbrain-network-confirmation.service', 'elderbrain-network-recovery.service',
           'elderbrain-admin-console.service', 'etc-netplan.mount', 'etc-ssh.mount', 'root-.ssh.mount',
           'home-elderbrain\\x2dinstaller-.ssh.mount')
UNITS = ('elderbrain-update-recovery.service', 'elderbrain-update-finish.service')


def files():
    targets = {'usr/libexec/elderbrain-recovery.py': 'bootstrap/recovery-launcher.py',
               'etc/systemd/system/elderbrain-storage.service': 'units/elderbrain-storage.service'}
    targets.update({'etc/systemd/system/' + name: 'bootstrap/' + name for name in UNITS})
    targets.update({'etc/systemd/system/' + name + '.d/20-update-recovery.conf':
                    'bootstrap/writer-recovery.conf' for name in WRITERS})
    return targets


def directory(path, root, *, create=False, mode=0o755):
    """Check each descendant; never follow an alias or relax existing permissions."""
    if not path.is_relative_to(root) or root.resolve() != root:
        raise ValueError('Bootstrap path is outside canonical host root')
    current = root
    for part in (None, *path.relative_to(root).parts):
        if part is not None:
            current = current / part
        if not current.exists() and not current.is_symlink():
            if not create:
                return
            current.mkdir(mode=mode if current == path else 0o755)
            sync_directory(current.parent)
        info = current.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o022):
            raise ValueError('Unsafe bootstrap directory')
    if mode == 0o700 and stat.S_IMODE(path.stat().st_mode) != mode:
        raise ValueError('Recovery history must be private')


def existing(path):
    if not path.exists() and not path.is_symlink():
        return None
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o7022):
        raise ValueError('Unsafe bootstrap target')
    # Empty managed files are valid previous state, unlike release metadata.
    if info.st_size == 0:
        return b''
    return read_regular(path, 4 * 1024 ** 2)


def publish(path, value, mode):
    descriptor, temporary = tempfile.mkstemp(prefix='.bootstrap-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def verify_installed(tree, allowed_paths, *, host_root=Path('/')):
    """Read-only prerequisite proof; caller holds maintenance and trusts tree."""
    root, tree = Path(host_root).absolute(), Path(tree).absolute()
    if tree.resolve() != tree:
        raise ValueError('Recovery proof source must be canonical')
    paths = inventory(allowed_paths)
    recovery = private_directory(root / 'usr/lib/elderbrain-recovery')
    descriptors = {}
    for name in sorted(paths):
        if Path(name).parent == Path('runtime') and name.endswith('.py'):
            source = tree / name
            if source.resolve() != source:
                raise ValueError('Aliased recovery proof source')
            value = read_regular(source, 4 * 1024 ** 2)
            descriptors[source.name] = {'size': len(value), 'sha256': hashlib.sha256(value).hexdigest()}
    if not {'release_recovery.py', 'release_baseline_install.py'} <= set(descriptors):
        raise ValueError('Recovery proof lacks migration entry points')
    manifest = json.dumps({'format': 1, 'entrypoint': 'release_recovery.py', 'files': descriptors},
                          sort_keys=True, separators=(',', ':')).encode()
    identity = hashlib.sha256(manifest).hexdigest()
    for name in ('active.json', 'installation.json'):
        info = (recovery / name).lstat()
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError('Recovery proof metadata must be private')
    selector = json.loads(read_regular(recovery / 'active.json', 65536))
    receipt = json.loads(read_regular(recovery / 'installation.json', 65536))
    if (selector != {'format': 1, 'bundle': identity} or type(selector['format']) is not int
            or not isinstance(receipt, dict) or type(receipt.get('format')) is not int or receipt['format'] != 1
            or receipt.get('state') != 'installed' or receipt.get('bundle') != identity):
        raise ValueError('Matching recovery bootstrap is not completely installed')
    manifest_info = (recovery / identity / 'bundle.json').lstat()
    if manifest_info.st_uid != os.geteuid() or stat.S_IMODE(manifest_info.st_mode) != 0o600:
        raise ValueError('Recovery proof manifest must be private')
    verify_tree(recovery / identity, descriptors, manifest)
    for target, source in files().items():
        if paths.get(source) != 0o644 or (tree / source).resolve() != tree / source:
            raise ValueError('Missing reviewed recovery boot file')
        destination = root / target
        directory(destination.parent, root)
        if existing(destination) != read_regular(tree / source, 4 * 1024 ** 2):
            raise ValueError('Installed recovery boot file differs')
    for name in UNITS:
        target = root / 'etc/systemd/system/multi-user.target.wants' / name
        directory(target.parent, root)
        if not target.is_symlink() or os.readlink(target) != '../' + name:
            raise ValueError('Recovery boot unit is not enabled')
    return {'bundle': identity}


def install(tree, allowed_paths, *, state, host_root=Path('/'), job_owner=None):
    """Internal installer API: tree and inventory must already be authenticated."""
    root, tree, state = Path(host_root).absolute(), Path(tree).absolute(), Path(state)
    identity = persistent_identity(state, root)  # Before creating any directories.
    if identity is None:
        raise ValueError('Recovery bootstrap requires verified persistent storage')
    if tree.resolve() != tree or not tree.is_dir():
        raise ValueError('Bootstrap source must be canonical')
    paths = inventory(allowed_paths)
    contents = {}
    for target, source in files().items():
        source_path = tree / source
        if paths.get(source) != 0o644 or source_path.resolve() != source_path:
            raise ValueError('Bootstrap source is outside reviewed inventory')
        value = existing(source_path)
        if not value:
            raise ValueError('Missing bootstrap source')
        contents[target] = value
    links = {'etc/systemd/system/multi-user.target.wants/' + name: '../' + name for name in UNITS}
    bundle_root = root / 'usr/lib/elderbrain-recovery'
    with update_admission(state, owner=job_owner):
        maintenance = Maintenance(state / 'maintenance', None)
        # No bootstrap files change before all target types are checked. The
        # content-addressed bundle publication below cannot alter active code.
        for name in (*contents, *links):
            target = root / name
            directory(target.parent, root)
            if name in contents:
                existing(target)
            elif target.exists() or target.is_symlink():
                if not target.is_symlink() or os.readlink(target) != links[name]:
                    raise ValueError('Unexpected bootstrap enablement target')
        directory(bundle_root, root, create=True, mode=0o700)
        bundle = install_bundle(tree, paths, directory=bundle_root)
        with selection_window(bundle['id'], directory=bundle_root, maintenance=maintenance):
            if persistent_identity(state, root) != identity:
                raise ValueError('Persistent storage changed during bootstrap')
            history = bundle_root / ('installation-' + uuid.uuid4().hex)
            directory(history, root, create=True, mode=0o700)
            record = {'format': 1, 'state': 'installing', 'bundle': bundle['id'],
                      'history': history.name, 'activationReady': False, 'files': {}}
            save_record(bundle_root / 'installation.json', record)
            # Preserve all previous managed bytes before the first replacement.
            for index, name in enumerate(contents):
                target = root / name
                previous = existing(target)
                entry = {'existed': previous is not None}
                if previous is not None:
                    entry.update(backup=str(index), mode=stat.S_IMODE(target.stat().st_mode))
                    publish(history / str(index), previous, 0o600)
                record['files'][name] = entry
            save_record(history / 'previous.json', record)
            # Launcher first, then complete units, then writer gates. No service
            # is stopped or started; partial installations remain unready.
            for name, value in contents.items():
                target = root / name
                directory(target.parent, root, create=True)
                publish(target, value, 0o644)
            for name, destination in links.items():
                target = root / name
                directory(target.parent, root, create=True)
                if not target.is_symlink():
                    os.symlink(destination, target)
                    sync_directory(target.parent)
            if persistent_identity(state, root) != identity:
                raise ValueError('Persistent storage changed during bootstrap')
            record['state'] = 'installed'
            save_record(bundle_root / 'installation.json', record)
            return record
