"""Initialize verified storage identity after Curtin, before appliance writers.

Invoked from the payload root with python3 -m provisioning.storage_initialize.
Never creates the data mountpoint or replaces an existing volume identity.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
from uuid import uuid4

from appliance.lib.storage_guard import DATA_MOUNT, MARKER, read_identity, validate_identity, verify_mount


def publish_new(path, identity):
    """Durable create-if-absent; existing identity must match exactly."""
    path = Path(path)
    if path.exists() or path.is_symlink():
        if read_identity(path) != identity:
            raise ValueError('Refusing to replace existing storage identity')
        return
    fd, temporary = tempfile.mkstemp(prefix='.storage-identity-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(json.dumps(identity) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        # No overwrite if another writer creates it after the existence check.
        os.link(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def initialize(receipt, mount_document, *, target=DATA_MOUNT,
               expected_path='/etc/elderbrain/storage.json', read=read_identity,
               publish=publish_new):
    if (not isinstance(receipt, dict) or type(receipt.get('version')) is not int
            or receipt['version'] != 1 or receipt.get('mode') not in ('fresh', 'preserve')
            or not isinstance(receipt.get('serial'), str) or not receipt['serial'].strip()):
        raise ValueError('Missing or invalid installer storage receipt')
    mounts = mount_document.get('filesystems')
    if not isinstance(mounts, list) or len(mounts) != 1:
        raise ValueError('Expected the dedicated persistent data mount')
    if Path(target).is_symlink():
        raise ValueError('Data mountpoint must not be a symlink')
    if receipt['mode'] == 'preserve':
        identity = validate_identity(receipt.get('identity'))
        if identity['disk_serial'] != receipt['serial']:
            raise ValueError('Receipt and preserved identity disagree')
        verify_mount(mount_document, identity, identity, target)
        # Preserve must never create a missing marker or invent a new identity.
        if read(Path(target) / MARKER) != identity:
            raise ValueError('Preserved volume identity changed after installer selection')
    else:
        if receipt.get('identity') is not None:
            raise ValueError('Fresh receipt must not contain a preserved identity')
        identity = validate_identity(dict(
            product='mindflayer-elderbrain', layout_version=1,
            appliance_id=str(uuid4()), data_uuid=mounts[0].get('uuid'),
            disk_serial=receipt['serial']))
        verify_mount(mount_document, identity, identity, target)
        # A fresh filesystem must be empty. Never bless an existing volume as a
        # fresh install simply because its mount has the right filesystem type.
        if any(Path(target).iterdir()):
            raise ValueError('Fresh data filesystem is not empty; refusing initialization')
        publish(Path(target) / MARKER, identity)
    expected_path = Path(expected_path)
    expected_path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    publish(expected_path, identity)
    return identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Storage initialization requires root')
    receipt = json.loads(Path(args.receipt).read_text())
    result = subprocess.run(['findmnt', '--json', '--mountpoint', DATA_MOUNT,
                             '--output', 'TARGET,FSTYPE,UUID,FSROOT,OPTIONS'],
                            check=True, capture_output=True, text=True, timeout=15)
    initialize(receipt, json.loads(result.stdout))


if __name__ == '__main__':
    main()
