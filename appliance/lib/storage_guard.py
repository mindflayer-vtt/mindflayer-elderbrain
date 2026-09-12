"""Verify persistent storage before starting any appliance data writer.

No directory creation or fallback is allowed here. Install a root-owned expected
identity in /etc/elderbrain/storage.json and an identical identity at the root of
the Btrfs volume. The installer provisions these only after validating storage.
"""

import json
import os
from pathlib import Path
import stat
import subprocess
from uuid import UUID

DATA_MOUNT = '/var/lib/mindflayer-elderbrain'
MARKER = '.elderbrain-volume.json'
IDENTITY_FIELDS = ('product', 'layout_version', 'appliance_id', 'data_uuid', 'disk_serial')


def read_identity(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or info.st_mode & 0o022 or info.st_size > 16384):
            raise ValueError('Storage identity must be a small root-owned, non-writable regular file')
        value = json.loads(stream.read(16385))
    return validate_identity(value)


def validate_identity(value):
    if (not isinstance(value, dict)
            or value.get('product') != 'mindflayer-elderbrain'
            or type(value.get('layout_version')) is not int
            or value['layout_version'] != 1
            or not isinstance(value.get('disk_serial'), str)
            or not value['disk_serial'].strip()):
        raise ValueError('Invalid persistent-storage identity')
    for field in ('appliance_id', 'data_uuid'):
        raw = value.get(field)
        if not isinstance(raw, str) or str(UUID(raw)) != raw:
            raise ValueError('Invalid persistent-storage UUID')
    return {field: value[field] for field in IDENTITY_FIELDS}


def verify_mount(document, expected, actual, target=DATA_MOUNT):
    expected = validate_identity(expected)
    actual = validate_identity(actual)
    mounts = document.get('filesystems')
    if not isinstance(mounts, list) or len(mounts) != 1:
        raise ValueError('Persistent data volume is missing or ambiguous')
    mount = mounts[0]
    options = set(str(mount.get('options', '')).split(','))
    if (mount.get('target') != target or mount.get('fstype') != 'btrfs'
            or mount.get('uuid') != expected['data_uuid']
            or mount.get('fsroot') != '/' or 'rw' not in options or 'ro' in options):
        raise ValueError('Persistent volume mount does not match the installed identity')
    if actual != expected:
        raise ValueError('Persistent volume marker does not match the installed identity')


def check(expected_path='/etc/elderbrain/storage.json', target=DATA_MOUNT,
          run=subprocess.run, read=read_identity):
    expected = read(expected_path)
    # --mountpoint (not --target) forbids silently matching the containing OS
    # filesystem when the dedicated data mount failed.
    result = run(['findmnt', '--json', '--mountpoint', target, '--output',
                  'TARGET,FSTYPE,UUID,FSROOT,OPTIONS'], check=True,
                 capture_output=True, text=True, timeout=15)
    document = json.loads(result.stdout)
    # Validate mount BEFORE reading a marker from the potentially wrong disk.
    verify_mount(document, expected, expected, target)
    if Path(target).is_symlink():
        raise ValueError('Persistent data mountpoint must not be a symlink')
    verify_mount(document, expected, read(Path(target) / MARKER), target)


if __name__ == '__main__':
    try:
        check()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(f'Persistent storage unavailable; refusing appliance startup: {error}')
