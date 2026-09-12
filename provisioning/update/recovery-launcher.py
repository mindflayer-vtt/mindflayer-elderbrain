#!/usr/bin/env python3
"""Minimal stdlib-only launcher: authenticate local bundle bytes before imports."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate recovery metadata field')
        result[key] = value
    return result


def private(path, directory=False):
    info = path.lstat()
    expected = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if (not expected or path.resolve() != path or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)):
        raise ValueError('Recovery path is not private and canonical')


def read(path, limit):
    private(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
            raise ValueError('Invalid recovery file size or type')
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Recovery file exceeds limit')
    return data


def selected(directory):
    directory = Path(directory).absolute()
    private(directory, directory=True)
    selection = json.loads(read(directory / 'active.json', 1024), object_pairs_hook=unique)
    if (not isinstance(selection, dict) or set(selection) != {'format', 'bundle'}
            or type(selection['format']) is not int or selection['format'] != 1
            or not isinstance(selection['bundle'], str) or not re.fullmatch(r'[a-f0-9]{64}', selection['bundle'])):
        raise ValueError('Invalid active recovery selection')
    bundle = directory / selection['bundle']
    private(bundle, directory=True)
    raw = read(bundle / 'bundle.json', 65536)
    if hashlib.sha256(raw).hexdigest() != selection['bundle']:
        raise ValueError('Recovery manifest hash differs from active selection')
    manifest = json.loads(raw, object_pairs_hook=unique)
    if (not isinstance(manifest, dict) or set(manifest) != {'format', 'entrypoint', 'files'}
            or type(manifest['format']) is not int or manifest['format'] != 1
            or manifest['entrypoint'] != 'release_recovery.py' or not isinstance(manifest['files'], dict)
            or not 1 <= len(manifest['files']) <= 256 or 'release_recovery.py' not in manifest['files']):
        raise ValueError('Invalid recovery bundle manifest')
    if {file.name for file in bundle.iterdir()} != set(manifest['files']) | {'bundle.json'}:
        raise ValueError('Unexpected or missing recovery modules')
    total = 0
    for name, expected in manifest['files'].items():
        if (not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*\.py', name) or not isinstance(expected, dict)
                or set(expected) != {'size', 'sha256'} or type(expected['size']) is not int
                or not 0 < expected['size'] <= 4 * 1024 ** 2 or not isinstance(expected['sha256'], str)
                or not re.fullmatch(r'[a-f0-9]{64}', expected['sha256'])):
            raise ValueError('Invalid recovery module descriptor')
        total += expected['size']
        if total > 64 * 1024 ** 2:
            raise ValueError('Recovery bundle exceeds limit')
        data = read(bundle / name, expected['size'])
        if len(data) != expected['size'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
            raise ValueError('Recovery module hash differs')
    return bundle / 'release_recovery.py'


def launch(phase, directory=Path('/usr/lib/elderbrain-recovery')):
    if phase not in ('storage', 'files', 'finish'):
        raise ValueError('Invalid recovery phase')
    entrypoint = selected(directory)
    arguments = [str(entrypoint), phase]
    if phase == 'storage':
        guard = entrypoint.parent / 'storage_guard.py'
        if not guard.is_file():
            raise ValueError('Verified recovery bundle has no storage guard')
        arguments = [str(guard)]
    os.execve('/usr/bin/python3', ['/usr/bin/python3', '-I', '-B', *arguments],
              {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('storage', 'files', 'finish'))
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Update recovery requires root')
    launch(args.phase)
