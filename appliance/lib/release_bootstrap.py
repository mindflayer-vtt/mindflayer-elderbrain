"""Install fixed recovery boot prerequisites from a caller-authenticated tree.

This does not authenticate archives, activate a release, or start services.
Bootstrap completion is not update readiness: migration and qualification of the
previous runtime are still required before admitting an update.
"""
import os
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import uuid

from backup_service import Maintenance, save_record
from release_interlocks import update_admission
from release_prepare import sync_directory
from appliance_release import unique
from release_recovery_bundle import (RECOVERY_API, active as active_bundle, install as install_bundle,
                                     verify_bundle, verify_tree)
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
GENERATIONS = 'bootstrap-generations'
ACTIVE = 'bootstrap-active'


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
    """Atomically publish a non-bootstrap runtime file for baseline migration."""
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


def source_contents(tree, paths):
    contents = {}
    for target, source in files().items():
        source_path = tree / source
        if paths.get(source) != 0o644 or source_path.resolve() != source_path:
            raise ValueError('Bootstrap source is outside reviewed inventory')
        value = existing(source_path)
        if not value:
            raise ValueError('Missing bootstrap source')
        contents[target] = value
    return contents


def generation_manifest(contents, bundle, recovery_api):
    if (not isinstance(bundle, str) or not re.fullmatch(r'[a-f0-9]{64}', bundle)
            or type(recovery_api) is not int or recovery_api != RECOVERY_API
            or set(contents) != set(files())):
        raise ValueError('Invalid bootstrap generation inputs')
    try:
        compile(contents['usr/libexec/elderbrain-recovery.py'],
                'usr/libexec/elderbrain-recovery.py', 'exec')
    except (SyntaxError, ValueError) as error:
        raise ValueError('Invalid bootstrap launcher') from error
    descriptors = {name: {'mode': 0o644, 'size': len(value),
                          'sha256': hashlib.sha256(value).hexdigest()}
                   for name, value in sorted(contents.items())}
    return json.dumps({'format': 1, 'recoveryApi': recovery_api, 'bundle': bundle,
                       'files': descriptors}, sort_keys=True, separators=(',', ':')).encode()


def selection_bytes(bundle):
    return json.dumps({'format': 1, 'bundle': bundle},
                      sort_keys=True, separators=(',', ':')).encode() + b'\n'


def verify_generation(identity, *, directory):
    if not isinstance(identity, str) or not re.fullmatch(r'[a-f0-9]{64}', identity):
        raise ValueError('Invalid bootstrap generation identity')
    directory = private_directory(Path(directory))
    generations = private_directory(directory / GENERATIONS)
    generation = private_directory(generations / identity)
    for name in ('generation.json', 'active.json'):
        info = (generation / name).lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise ValueError('Bootstrap generation metadata must be private')
    raw = read_regular(generation / 'generation.json', 65536)
    if hashlib.sha256(raw).hexdigest() != identity:
        raise ValueError('Bootstrap generation identity differs')
    value = json.loads(raw, object_pairs_hook=unique)
    if (not isinstance(value, dict) or set(value) != {'format', 'recoveryApi', 'bundle', 'files'}
            or type(value['format']) is not int or value['format'] != 1
            or type(value['recoveryApi']) is not int or value['recoveryApi'] != RECOVERY_API
            or not isinstance(value['bundle'], str) or not re.fullmatch(r'[a-f0-9]{64}', value['bundle'])
            or not isinstance(value['files'], dict) or set(value['files']) != set(files())):
        raise ValueError('Invalid bootstrap generation manifest')
    expected_paths = {'generation.json', 'active.json'}
    for name, expected in value['files'].items():
        if (not isinstance(expected, dict) or set(expected) != {'mode', 'size', 'sha256'}
                or type(expected['mode']) is not int or expected['mode'] != 0o644
                or type(expected['size']) is not int or not 0 < expected['size'] <= 4 * 1024 ** 2
                or not isinstance(expected['sha256'], str)
                or not re.fullmatch(r'[a-f0-9]{64}', expected['sha256'])):
            raise ValueError('Invalid bootstrap file descriptor')
        path = generation / 'root' / name
        data = read_regular(path, 4 * 1024 ** 2)
        info = path.lstat()
        if (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != expected['mode']
                or len(data) != expected['size'] or hashlib.sha256(data).hexdigest() != expected['sha256']):
            raise ValueError('Bootstrap generation file differs')
        expected_paths.add(('root/' + name))
    selection_raw = read_regular(generation / 'active.json', 1024)
    selection = json.loads(selection_raw, object_pairs_hook=unique)
    if selection != {'format': 1, 'bundle': value['bundle']} or type(selection['format']) is not int:
        raise ValueError('Bootstrap generation recovery selection differs')
    if selection_raw != selection_bytes(value['bundle']):
        raise ValueError('Bootstrap generation recovery selection is not canonical')
    for path in generation.rglob('*'):
        relative = path.relative_to(generation).as_posix()
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            if info.st_uid != os.geteuid() or info.st_mode & 0o022:
                raise ValueError('Unsafe bootstrap generation directory')
        elif relative not in expected_paths or not stat.S_ISREG(info.st_mode):
            raise ValueError('Bootstrap generation contains unexpected entries')
    present = {path.relative_to(generation).as_posix() for path in generation.rglob('*') if path.is_file()}
    if present != expected_paths:
        raise ValueError('Bootstrap generation contains unexpected or missing files')
    verify_bundle(value['bundle'], directory=directory)
    return {'id': identity, 'bundle': value['bundle'], 'recoveryApi': value['recoveryApi']}


def install_generation(contents, bundle, *, directory, recovery_api=RECOVERY_API):
    directory = private_directory(Path(directory))
    generations = directory / GENERATIONS
    if not generations.exists() and not generations.is_symlink():
        generations.mkdir(mode=0o700)
        sync_directory(directory)
    generations = private_directory(generations)
    raw = generation_manifest(contents, bundle, recovery_api)
    identity = hashlib.sha256(raw).hexdigest()
    destination = generations / identity
    if destination.exists() or destination.is_symlink():
        return verify_generation(identity, directory=directory)
    with tempfile.TemporaryDirectory(prefix='.bootstrap-generation-', dir=generations) as temporary:
        work = Path(temporary) / 'generation'
        work.mkdir(mode=0o700)
        for name, value in {**contents, 'active.json': selection_bytes(bundle),
                'generation.json': raw}.items():
            path = work / ('root/' + name if name in contents else name)
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with path.open('xb') as stream:
                os.fchmod(stream.fileno(), 0o644 if name in contents else 0o600)
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
        for path in sorted((item for item in work.rglob('*') if item.is_dir()),
                           key=lambda item: len(item.parts), reverse=True):
            sync_directory(path)
        sync_directory(work)
        os.rename(work, destination)
        sync_directory(generations)
    return verify_generation(identity, directory=directory)


def active_generation(*, directory):
    directory = private_directory(Path(directory))
    current = directory / ACTIVE
    info = current.lstat()
    target = os.readlink(current) if stat.S_ISLNK(info.st_mode) else ''
    match = re.fullmatch(GENERATIONS + r'/([a-f0-9]{64})', target)
    if info.st_uid != os.geteuid() or match is None:
        raise ValueError('Invalid active bootstrap generation')
    return verify_generation(match.group(1), directory=directory)


def anchor(root, target):
    return os.path.relpath(root / 'usr/lib/elderbrain-recovery' / ACTIVE / 'root' / target,
                           (root / target).parent)


def verify_anchors(root, *, allow_missing=False):
    missing = []
    for name in files():
        target, expected = root / name, anchor(root, name)
        directory(target.parent, root)
        if not target.exists() and not target.is_symlink():
            if allow_missing:
                missing.append((target, expected))
                continue
            raise ValueError('Missing bootstrap generation anchor')
        info = target.lstat()
        if (not stat.S_ISLNK(info.st_mode) or info.st_uid != os.geteuid()
                or os.readlink(target) != expected):
            raise ValueError('Unsafe bootstrap generation anchor')
    return missing


def publish_generation(identity, *, directory):
    verify_generation(identity, directory=directory)
    target = GENERATIONS + '/' + identity
    current = Path(directory) / ACTIVE
    temporary = Path(directory) / ('.bootstrap-active-' + uuid.uuid4().hex)
    try:
        os.symlink(target, temporary)
        os.replace(temporary, current)
        sync_directory(Path(directory))
    finally:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()
    return {'generation': identity}


def reload_units(root, run=subprocess.run):
    """Refresh the live manager after an atomic online generation switch."""
    if Path(root) == Path('/'):
        run(['/usr/bin/systemctl', 'daemon-reload'], check=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=30)


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
    manifest = json.dumps({'format': 2, 'recoveryApi': RECOVERY_API,
                          'entrypoint': 'release_recovery.py', 'files': descriptors},
                          sort_keys=True, separators=(',', ':')).encode()
    identity = hashlib.sha256(manifest).hexdigest()
    info = (recovery / 'installation.json').lstat()
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError('Recovery proof metadata must be private')
    receipt = json.loads(read_regular(recovery / 'installation.json', 65536))
    contents = source_contents(tree, paths)
    generation_raw = generation_manifest(contents, identity, RECOVERY_API)
    generation_id = hashlib.sha256(generation_raw).hexdigest()
    if (not isinstance(receipt, dict) or type(receipt.get('format')) is not int or receipt['format'] != 2
            or receipt.get('state') != 'installed' or receipt.get('bundle') != identity
            or receipt.get('generation') != generation_id or receipt.get('activationReady') is not False):
        raise ValueError('Matching recovery bootstrap is not completely installed')
    manifest_info = (recovery / identity / 'bundle.json').lstat()
    if manifest_info.st_uid != os.geteuid() or stat.S_IMODE(manifest_info.st_mode) != 0o600:
        raise ValueError('Recovery proof manifest must be private')
    verify_tree(recovery / identity, descriptors, manifest)
    generation = active_generation(directory=recovery)
    if generation != {'id': generation_id, 'bundle': identity, 'recoveryApi': RECOVERY_API}:
        raise ValueError('Installed recovery bootstrap generation differs')
    verify_anchors(root)
    for name in UNITS:
        target = root / 'etc/systemd/system/multi-user.target.wants' / name
        directory(target.parent, root)
        if not target.is_symlink() or os.readlink(target) != '../' + name:
            raise ValueError('Recovery boot unit is not enabled')
    return {'bundle': identity}


def prepare_candidate(tree, allowed_paths, *, recovery_api, state, host_root=Path('/'), job_owner=None):
    """Install authenticated candidate recovery bytes without selecting them."""
    root, tree, state = Path(host_root).absolute(), Path(tree).absolute(), Path(state)
    identity = persistent_identity(state, root)
    if identity is None:
        raise ValueError('Recovery preparation requires verified persistent storage')
    if tree.resolve() != tree or not tree.is_dir():
        raise ValueError('Bootstrap source must be canonical')
    paths = inventory(allowed_paths)
    contents = source_contents(tree, paths)
    bundle_root = root / 'usr/lib/elderbrain-recovery'
    with update_admission(state, owner=job_owner):
        maintenance = Maintenance(state / 'maintenance', None)
        with maintenance.locked():
            if maintenance.previous().get('state') not in (None, 'completed', 'failed', 'recovered', 'rolled-back'):
                raise RuntimeError('Recover maintenance before preparing recovery code')
            verify_anchors(root)
            selected_generation = active_generation(directory=bundle_root)
            selected = active_bundle(directory=bundle_root)
            if selected_generation['bundle'] != selected['bundle']:
                raise ValueError('Active bootstrap generation and recovery authority differ')
            if selected['recoveryApi'] != recovery_api:
                raise ValueError('Release recovery API differs from the active transaction API')
            bundle = install_bundle(tree, paths, directory=bundle_root, recovery_api=recovery_api)
            generation = install_generation(contents, bundle['id'], directory=bundle_root,
                                            recovery_api=recovery_api)
            if persistent_identity(state, root) != identity:
                raise ValueError('Persistent storage changed during recovery preparation')
            return {'active': selected['bundle'], 'candidate': generation['id']}


def commit_candidate(identity, *, state, host_root=Path('/'), job_owner=None, run=subprocess.run):
    """Select a verified candidate only after its release transaction committed."""
    root, state = Path(host_root).absolute(), Path(state)
    storage = persistent_identity(state, root)
    if storage is None:
        raise ValueError('Recovery selection requires verified persistent storage')
    with update_admission(state, owner=job_owner):
        maintenance = Maintenance(state / 'maintenance', None)
        with maintenance.locked():
            if maintenance.previous().get('state') not in (None, 'completed', 'failed', 'recovered', 'rolled-back'):
                raise RuntimeError('Cannot change recovery code during unfinished maintenance')
            recovery = root / 'usr/lib/elderbrain-recovery'
            verify_anchors(root)
            generation = verify_generation(identity, directory=recovery)
            if persistent_identity(state, root) != storage:
                raise ValueError('Persistent storage changed during recovery selection')
            publish_generation(identity, directory=recovery)
            save_record(recovery / 'installation.json', {
                'format': 2, 'state': 'installed', 'bundle': generation['bundle'],
                'generation': identity, 'activationReady': False})
            reload_units(root, run)
            return {'bundle': generation['bundle'], 'generation': identity}


def verify_active(identity, recovery_api, *, host_root=Path('/')):
    """Prove the executing known-good bundle remains the active authority."""
    root = Path(host_root).absolute()
    selected = active_bundle(directory=root / 'usr/lib/elderbrain-recovery', expected=identity)
    if selected['recoveryApi'] != recovery_api:
        raise ValueError('Active recovery transaction API changed')
    return selected


def install(tree, allowed_paths, *, state, host_root=Path('/'), job_owner=None):
    """Internal installer API: tree and inventory must already be authenticated."""
    root, tree, state = Path(host_root).absolute(), Path(tree).absolute(), Path(state)
    identity = persistent_identity(state, root)  # Before creating any directories.
    if identity is None:
        raise ValueError('Recovery bootstrap requires verified persistent storage')
    if tree.resolve() != tree or not tree.is_dir():
        raise ValueError('Bootstrap source must be canonical')
    paths = inventory(allowed_paths)
    contents = source_contents(tree, paths)
    links = {'etc/systemd/system/multi-user.target.wants/' + name: '../' + name for name in UNITS}
    bundle_root = root / 'usr/lib/elderbrain-recovery'
    with update_admission(state, owner=job_owner):
        maintenance = Maintenance(state / 'maintenance', None)
        directory(bundle_root, root, create=True, mode=0o700)
        bundle = install_bundle(tree, paths, directory=bundle_root, recovery_api=RECOVERY_API)
        generation = install_generation(contents, bundle['id'], directory=bundle_root)
        with maintenance.locked():
            if maintenance.previous().get('state') not in (None, 'completed', 'failed', 'recovered', 'rolled-back'):
                raise RuntimeError('Recover maintenance before installing recovery bootstrap')
            if persistent_identity(state, root) != identity:
                raise ValueError('Persistent storage changed during bootstrap')
            current = bundle_root / ACTIVE
            has_current = current.exists() or current.is_symlink()
            missing = verify_anchors(root, allow_missing=not has_current)
            if has_current:
                active_generation(directory=bundle_root)
            # Clean installation creates stable indirections before publishing
            # a selector. An interrupted first install therefore exposes no
            # partially selected generation and safely converges on rerun.
            for target, destination in missing:
                directory(target.parent, root, create=True)
                os.symlink(destination, target)
                sync_directory(target.parent)
            for name, destination in links.items():
                target = root / name
                directory(target.parent, root, create=True)
                if target.exists() or target.is_symlink():
                    if not target.is_symlink() or os.readlink(target) != destination:
                        raise ValueError('Unexpected bootstrap enablement target')
                else:
                    os.symlink(destination, target)
                    sync_directory(target.parent)
            if persistent_identity(state, root) != identity:
                raise ValueError('Persistent storage changed during bootstrap')
            publish_generation(generation['id'], directory=bundle_root)
            record = {'format': 2, 'state': 'installed', 'bundle': bundle['id'],
                      'generation': generation['id'], 'activationReady': False}
            save_record(bundle_root / 'installation.json', record)
            return record
