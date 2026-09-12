"""Private, bounded host package staging; never writes an installation target."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tarfile
import tempfile

from appliance_release import verify, verify_artifact

EXPANDED_LIMIT = 512 * 1024 ** 2
FILE_LIMIT = 64 * 1024 ** 2
COUNT_LIMIT = 4096


def safe_name(name):
    if (not isinstance(name, str) or not name or len(name) > 240
            or '\\' in name or '\0' in name or name.startswith('/')):
        raise ValueError('Unsafe host package path')
    parts = name.split('/')
    if any(part in ('', '.', '..') for part in parts) or str(PurePosixPath(name)) != name:
        raise ValueError('Unsafe host package path')
    return name


def inventory(paths):
    """Trusted installer supplies exact paths/modes, not a manifest-provided map."""
    if not isinstance(paths, dict) or not 1 <= len(paths) <= COUNT_LIMIT:
        raise ValueError('Invalid trusted host inventory')
    for name, mode in paths.items():
        safe_name(name)
        if type(mode) is not int or mode not in (0o644, 0o755):
            raise ValueError('Unsupported host package mode')
        if any(str(parent) in paths for parent in PurePosixPath(name).parents if str(parent) != '.'):
            raise ValueError('Host inventory file/directory collision')
    return dict(paths)


@contextmanager
def stage(archive, manifest, signature, public_key, allowed_paths=None, *, parent, component='host'):
    """Yield verified release and staged tree for the lifetime of this context.

Parent must be a private staging directory owned by the caller. A new temporary
tree prevents links or leftovers from earlier failed releases being reused.
Callers must never supply live runtime/configuration as the inventory root.
"""
    release = verify(manifest, signature, public_key)
    if component not in ('host', 'dependencies') or component not in release:
        raise ValueError('Unsupported release artifact component')
    if component == 'dependencies':
        signed_paths = {name: 0o644 for name in release['dependencies']['files']}
        if allowed_paths is not None and allowed_paths != signed_paths:
            raise ValueError('Dependency inventory differs from signed manifest')
        allowed_paths = signed_paths
    paths = inventory(allowed_paths)
    parent = Path(parent)
    info = parent.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077
            or parent.resolve() != parent.absolute()):
        raise ValueError('Release staging parent must be private and canonical')
    with tempfile.TemporaryDirectory(prefix='release-stage-', dir=parent) as temporary:
        root = Path(temporary)
        copied = root / (component + '.tar.zst')
        descriptor = os.open(archive, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as source, copied.open('xb') as output:
            info = os.fstat(source.fileno())
            size = release[component]['artifact']['size']
            if not stat.S_ISREG(info.st_mode) or info.st_size != size:
                raise ValueError('Host artifact size or type mismatch')
            os.fchmod(output.fileno(), 0o600)
            remaining = size
            while remaining:
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError('Truncated host archive')
                output.write(chunk)
                remaining -= len(chunk)
            if source.read(1):
                raise ValueError('Host archive grew during copy')
        verify_artifact(copied, release, component)  # Verify the private copy we unpack.
        tar = root / 'host.tar'
        with tar.open('xb') as output:
            os.fchmod(output.fileno(), 0o600)
            # Kernel-enforced output bound plus a process deadline, without
            # preexec_fn in the threaded management process or shell evaluation.
            subprocess.run(['prlimit', f'--fsize={EXPANDED_LIMIT}:{EXPANDED_LIMIT}', '--core=0:0', '--',
                            'zstd', '-q', '-d', '-c', str(copied)], stdout=output,
                           stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, check=True, timeout=120)
        with tarfile.open(tar, mode='r:') as package:
            members = {}
            total = 0
            for member in package:
                name = safe_name(member.name)
                safe_metadata = (not member.pax_headers or (component == 'dependencies'
                                 and member.pax_headers == {'path': name}))
                if (name not in paths or name in members or not member.isfile()
                        or member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE)
                        or not safe_metadata or member.mode & 0o7000
                        or not 0 <= member.size <= FILE_LIMIT):
                    raise ValueError('Unexpected or unsafe host archive member')
                members[name] = member
                total += member.size
                if len(members) > COUNT_LIMIT or total > EXPANDED_LIMIT:
                    raise ValueError('Host archive exceeds unpacked limits')
            if set(members) != set(paths):
                raise ValueError('Host archive does not match the trusted inventory')
            tree = root / 'tree'
            tree.mkdir(mode=0o700)
            for name, member in members.items():
                target = tree / name
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with package.extractfile(member) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                    output.flush()
                    os.fchmod(output.fileno(), paths[name])
                    os.fsync(output.fileno())
                if component == 'dependencies':
                    expected = release['dependencies']['files'][name]
                    if target.stat().st_size != expected['size'] or hashlib.sha256(target.read_bytes()).hexdigest() != expected['sha256']:
                        raise ValueError('Dependency file differs from signed inventory')
        yield release, tree
