#!/usr/bin/env python3
"""Build an unsigned deterministic host code archive from reviewed source paths."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'appliance/lib'))
from appliance_release import VERSION, unique
from release_staging import inventory, safe_name, FILE_LIMIT, EXPANDED_LIMIT


def entries(file):
    values = json.loads(Path(file).read_text(), object_pairs_hook=unique)
    if not isinstance(values, list) or not values:
        raise ValueError('Invalid reviewed host inventory')
    sources, paths = set(), {}
    for value in values:
        if not isinstance(value, dict) or set(value) != {'source', 'path', 'mode'}:
            raise ValueError('Invalid host inventory entry')
        source = safe_name(value['source'])
        target = safe_name(value['path'])
        if source in sources or target in paths or target == 'runtime/VERSION':
            raise ValueError('Duplicate or reserved host inventory entry')
        sources.add(source)
        paths[target] = value['mode']
    inventory({**paths, 'runtime/VERSION': 0o644})
    return sorted(values, key=lambda value: value['path'])


def build(source_root, inventory_file, destination, version):
    if not isinstance(version, str) or not re.fullmatch(VERSION, version):
        raise ValueError('Stable host component version required')
    source_root = Path(source_root).resolve()
    destination = Path(destination)
    selected = entries(inventory_file)
    if destination.name != 'elderbrain-host.tar.zst':
        raise ValueError('Use the fixed host artifact filename')
    with tempfile.TemporaryDirectory(prefix='host-package-', dir=destination.parent) as temporary:
        root = Path(temporary)
        raw = root / 'host.tar'
        total = 0
        with tarfile.open(raw, 'w', format=tarfile.USTAR_FORMAT) as package:
            def add(name, data, mode):
                nonlocal total
                total += len(data)
                if len(data) > FILE_LIMIT or total > EXPANDED_LIMIT // 2:
                    raise ValueError('Host source package exceeds limits')
                member = tarfile.TarInfo(name)
                member.size, member.mode = len(data), mode
                member.uid = member.gid = member.mtime = 0
                package.addfile(member, io.BytesIO(data))
            add('runtime/VERSION', (version + '\n').encode(), 0o644)
            for entry in selected:
                source = source_root / entry['source']
                if source.resolve() != source:
                    raise ValueError('Host package source symlink rejected')
                descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(descriptor, 'rb') as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size > FILE_LIMIT:
                        raise ValueError('Invalid host package source type or size')
                    add(entry['path'], stream.read(FILE_LIMIT + 1), entry['mode'])
        packed = root / 'host.tar.zst'
        with packed.open('xb') as output:
            subprocess.run(['zstd', '-q', '-T1', '-19', '-c', str(raw)], stdout=output,
                           stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, check=True, timeout=120)
            output.flush()
            os.fsync(output.fileno())
        digest = hashlib.sha256(packed.read_bytes()).hexdigest()
        size = packed.stat().st_size
        os.link(packed, destination)  # Atomic publication; never overwrite an artifact.
        descriptor = os.open(destination.parent, os.O_DIRECTORY | os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return {'file': destination.name, 'size': size, 'sha256': digest}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT)
    parser.add_argument('--inventory', type=Path, default=ROOT / 'release/host-files.json')
    parser.add_argument('--version', required=True)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.inventory, args.destination, args.version)))
