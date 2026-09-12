"""Package freshly built dependency inputs; caller signs returned metadata."""
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'appliance/lib'))
from appliance_release import unique, validate_dependencies


def describe(directory):
    directory = Path(directory).resolve()
    index = directory / 'dependencies.json'
    if index.is_symlink() or index.stat().st_size > 65536:
        raise ValueError('Invalid dependency build receipt')
    receipt = json.loads(index.read_bytes(), object_pairs_hook=unique)
    if (receipt.get('format') != 1 or receipt.get('platform') !=
            {'os': 'ubuntu', 'release': '26.04', 'architecture': 'amd64'}
            or not str(receipt.get('python', '')).startswith('3.14.')):
        raise ValueError('Dependency build target differs from release platform')
    files = dict(receipt['files'])
    if 'dependencies.json' in files:
        raise ValueError('Dependency receipt cannot describe itself')
    files['dependencies.json'] = {'size': index.stat().st_size, 'sha256': hashlib.sha256(index.read_bytes()).hexdigest()}
    value = validate_dependencies({'pythonAbi': 'cp314', 'files': files, 'artifact': {
        'file': 'elderbrain-dependencies.tar.zst', 'size': 1, 'sha256': '0' * 64}})
    actual = {str(file.relative_to(directory)) for file in directory.rglob('*') if not file.is_dir()}
    if actual != set(files):
        raise ValueError('Unexpected dependency bundle files')
    return value


def pack(directory, destination):
    directory, destination = Path(directory).resolve(), Path(destination)
    value = describe(directory)
    if destination.name != 'elderbrain-dependencies.tar.zst':
        raise ValueError('Invalid dependency artifact filename')
    with tempfile.TemporaryDirectory(prefix='dependency-package-', dir=destination.parent) as temporary:
        raw = Path(temporary) / 'dependencies.tar'
        # Wheel platform tags can exceed USTAR's 100-byte filename field.
        # PAX emits only a path extension for these normalized integer headers.
        with tarfile.open(raw, 'w', format=tarfile.PAX_FORMAT) as package:
            for name, expected in sorted(value['files'].items()):
                file = directory / name
                if file.resolve() != file:
                    raise ValueError('Dependency source symlink rejected')
                descriptor = os.open(file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(descriptor, 'rb') as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        raise ValueError('Invalid dependency artifact type')
                    data = stream.read(expected['size'] + 1)
                if len(data) != expected['size'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
                    raise ValueError('Dependency bytes differ from build receipt')
                member = tarfile.TarInfo(name)
                member.size, member.mode = len(data), 0o644
                package.addfile(member, io.BytesIO(data))
        with destination.open('xb') as output:
            subprocess.run(['zstd', '-q', '-T1', '-19', '-c', str(raw)], stdout=output,
                           stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, check=True, timeout=120)
            output.flush()
            os.fsync(output.fileno())
    value['artifact'].update(size=destination.stat().st_size, sha256=hashlib.sha256(destination.read_bytes()).hexdigest())
    return validate_dependencies(value)
