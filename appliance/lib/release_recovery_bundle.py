"""Retain trusted recovery modules outside the replaceable runtime directory."""
import fcntl
from contextlib import contextmanager
import hashlib
import json
import os
import re
from pathlib import Path
import stat
import subprocess
import tempfile

from release_prepare import sync_directory
from release_runtime import private_directory, read_regular
from release_staging import inventory
from appliance_release import unique
from backup_service import save_record


def verify_tree(directory, files, manifest):
    directory = private_directory(directory)
    if {path.name for path in directory.iterdir()} != set(files) | {'bundle.json'}:
        raise ValueError('Recovery bundle contains unexpected or missing files')
    if read_regular(directory / 'bundle.json', 65536) != manifest:
        raise ValueError('Recovery bundle manifest differs')
    for name, expected in files.items():
        file = directory / name
        info = file.lstat()
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError('Recovery module permissions changed')
        data = read_regular(file, 4 * 1024 ** 2)
        if len(data) != expected['size'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
            raise ValueError('Recovery module bytes differ')


def select(identity, *, directory, maintenance):
    with selection_window(identity, directory=directory, maintenance=maintenance) as result:
        return result


def verify_bundle(identity, *, directory):
    if not isinstance(identity, str) or not re.fullmatch(r'[a-f0-9]{64}', identity):
        raise ValueError('Invalid recovery bundle identity')
    directory = private_directory(directory)
    bundle = private_directory(directory / identity)
    manifest = read_regular(bundle / 'bundle.json', 65536)
    if hashlib.sha256(manifest).hexdigest() != identity:
        raise ValueError('Recovery manifest identity differs')
    value = json.loads(manifest, object_pairs_hook=unique)
    if (not isinstance(value, dict) or set(value) != {'format', 'entrypoint', 'files'}
            or type(value['format']) is not int or value['format'] != 1
            or value['entrypoint'] != 'release_recovery.py' or not isinstance(value['files'], dict)
            or not 1 <= len(value['files']) <= 256 or 'release_recovery.py' not in value['files']):
        raise ValueError('Invalid recovery bundle manifest')
    for name, item in value['files'].items():
        if (not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*\.py', name) or not isinstance(item, dict)
                or set(item) != {'size', 'sha256'} or type(item['size']) is not int
                or not 0 < item['size'] <= 4 * 1024 ** 2 or not isinstance(item['sha256'], str)
                or not re.fullmatch(r'[a-f0-9]{64}', item['sha256'])):
            raise ValueError('Invalid recovery module descriptor')
    if sum(item['size'] for item in value['files'].values()) > 64 * 1024 ** 2:
        raise ValueError('Recovery bundle exceeds limit')
    verify_tree(bundle, value['files'], manifest)
    return value


def active(*, directory, expected=None):
    directory = private_directory(directory)
    selection = json.loads(read_regular(directory / 'active.json', 1024), object_pairs_hook=unique)
    if (not isinstance(selection, dict) or set(selection) != {'format', 'bundle'}
            or type(selection['format']) is not int or selection['format'] != 1
            or not isinstance(selection['bundle'], str)):
        raise ValueError('Invalid active recovery selection')
    if expected is not None and selection['bundle'] != expected:
        raise ValueError('Running recovery bundle is no longer active')
    verify_bundle(selection['bundle'], directory=directory)
    return {'bundle': selection['bundle']}


@contextmanager
def selection_window(identity, *, directory, maintenance):
    """Caller verified storage; serialized selection cannot change mid-update."""
    directory = private_directory(directory)
    with maintenance.locked():
        if maintenance.previous().get('state') not in (None, 'completed', 'failed', 'recovered', 'rolled-back'):
            raise RuntimeError('Cannot change recovery code during unfinished maintenance')
        verify_bundle(identity, directory=directory)
        yield {'bundle': identity}
        # Publication is the commit point. A caller failure while installing
        # bootstrap files or rechecking storage leaves the old authority active.
        save_record(directory / 'active.json', {'format': 1, 'bundle': identity})


def install(tree, allowed_paths, *, directory, run=subprocess.run):
    """Caller supplies a trusted authenticated host tree and reviewed inventory.

This is not an archive verifier or trust-key installer. The caller must stage the
known recovery implementation before any update is admitted. No active selector
or boot unit is changed here; existing bundles are verified, never overwritten.
"""
    tree = Path(tree).absolute()
    if tree.resolve() != tree or not tree.is_dir():
        raise ValueError('Recovery source must be a canonical authenticated tree')
    directory = private_directory(directory)
    if directory.is_relative_to(tree) or tree.is_relative_to(directory):
        raise ValueError('Recovery bundles must be separate from source runtime trees')
    paths = inventory(allowed_paths)
    selected = {Path(name).name: name for name in paths
                if Path(name).parent == Path('runtime') and name.endswith('.py')}
    if 'release_recovery.py' not in selected or not 1 <= len(selected) <= 256:
        raise ValueError('Recovery inventory requires its entry point and bounded module set')
    contents, files = {}, {}
    total = 0
    for name, relative in sorted(selected.items()):
        source = tree / relative
        if source.resolve() != source:
            raise ValueError('Recovery source symlinks are not allowed')
        data = read_regular(source, 4 * 1024 ** 2)
        total += len(data)
        if total > 64 * 1024 ** 2:
            raise ValueError('Recovery module set exceeds size limit')
        contents[name] = data
        files[name] = {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    manifest = json.dumps({'format': 1, 'entrypoint': 'release_recovery.py', 'files': files},
                          sort_keys=True, separators=(',', ':')).encode()
    if len(manifest) > 65536:
        raise ValueError('Recovery manifest exceeds limit')
    identity = hashlib.sha256(manifest).hexdigest()
    destination = directory / identity
    descriptor = os.open(directory / '.install.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if destination.exists() or destination.is_symlink():
            verify_tree(destination, files, manifest)
            return {'id': identity, 'directory': str(destination)}
        with tempfile.TemporaryDirectory(prefix='.recovery-', dir=directory) as temporary:
            work = Path(temporary)
            staged = work / 'bundle'
            staged.mkdir(mode=0o700)
            for name, data in {**contents, 'bundle.json': manifest}.items():
                file = staged / name
                with file.open('xb') as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
            # Import the full dependency closure with no live-runtime search path
            # and no bytecode writes. This does not call either recovery phase.
            run(['/usr/bin/python3', '-I', '-B', '-c',
                 'import sys; sys.path.insert(0,sys.argv[1]); import release_recovery; '
                 'assert callable(release_recovery.recover)', str(staged)], check=True,
                env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'}, cwd=work,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
            verify_tree(staged, files, manifest)
            sync_directory(staged)
            os.rename(staged, destination)
            sync_directory(directory)
        return {'id': identity, 'directory': str(destination)}
    finally:
        os.close(descriptor)
