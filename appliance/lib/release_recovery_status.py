"""Small read-only verifier for the active recovery authority.

This module deliberately uses only the standard library so the clean-install
management runtime can check release compatibility without importing the full
privileged activation implementation.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat


def unique(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError('Duplicate recovery metadata field')
        value[key] = item
    return value


def private_directory(path):
    path = Path(path).absolute()
    info = path.lstat()
    if (path.resolve() != path or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid() or info.st_mode & 0o077):
        raise ValueError('Recovery status requires private canonical directories')
    return path


def regular(path, limit, *, mode=None):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or (mode is not None and stat.S_IMODE(info.st_mode) != mode)
                or not 0 < info.st_size <= limit):
            raise ValueError('Invalid recovery status file')
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Recovery status file exceeds limit')
    return data


def bundle(identity, directory):
    if not isinstance(identity, str) or not re.fullmatch(r'[a-f0-9]{64}', identity):
        raise ValueError('Invalid recovery bundle identity')
    directory = private_directory(directory)
    selected = private_directory(directory / identity)
    manifest = regular(selected / 'bundle.json', 65536, mode=0o600)
    if hashlib.sha256(manifest).hexdigest() != identity:
        raise ValueError('Recovery manifest identity differs')
    value = json.loads(manifest, object_pairs_hook=unique)
    if (not isinstance(value, dict) or set(value) != {'format', 'recoveryApi', 'entrypoint', 'files'}
            or type(value['format']) is not int or value['format'] != 2
            or type(value['recoveryApi']) is not int or not 1 <= value['recoveryApi'] <= 65535
            or value['entrypoint'] != 'release_recovery.py' or not isinstance(value['files'], dict)
            or not 1 <= len(value['files']) <= 256 or 'release_recovery.py' not in value['files']):
        raise ValueError('Invalid recovery bundle manifest')
    if set(path.name for path in selected.iterdir()) != set(value['files']) | {'bundle.json'}:
        raise ValueError('Recovery bundle contains unexpected or missing files')
    total = 0
    for name, expected in value['files'].items():
        if (not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*\.py', name)
                or not isinstance(expected, dict) or set(expected) != {'size', 'sha256'}
                or type(expected['size']) is not int or not 0 < expected['size'] <= 4 * 1024 ** 2
                or not isinstance(expected['sha256'], str) or not re.fullmatch(r'[a-f0-9]{64}', expected['sha256'])):
            raise ValueError('Invalid recovery module descriptor')
        data = regular(selected / name, 4 * 1024 ** 2, mode=0o600)
        total += len(data)
        if len(data) != expected['size'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
            raise ValueError('Recovery module bytes differ')
    if total > 64 * 1024 ** 2:
        raise ValueError('Recovery bundle exceeds limit')
    return {'bundle': identity, 'recoveryApi': value['recoveryApi']}


def active(*, directory, expected=None):
    directory = private_directory(directory)
    current = directory / 'bootstrap-active'
    info = current.lstat()
    target = os.readlink(current) if stat.S_ISLNK(info.st_mode) else ''
    match = re.fullmatch(r'bootstrap-generations/([a-f0-9]{64})', target)
    if info.st_uid != os.geteuid() or match is None:
        raise ValueError('Invalid active bootstrap generation')
    generation = private_directory(directory / 'bootstrap-generations' / match.group(1))
    if current.resolve() != generation:
        raise ValueError('Active bootstrap generation escapes its store')
    raw = regular(generation / 'active.json', 1024, mode=0o600)
    selection = json.loads(raw, object_pairs_hook=unique)
    if (not isinstance(selection, dict) or set(selection) != {'format', 'bundle'}
            or type(selection['format']) is not int or selection['format'] != 1
            or not isinstance(selection['bundle'], str)):
        raise ValueError('Invalid active recovery selection')
    if expected is not None and selection['bundle'] != expected:
        raise ValueError('Running recovery bundle is no longer active')
    return bundle(selection['bundle'], directory)
