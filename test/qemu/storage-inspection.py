"""Root/private-namespace test of read-only existing-volume inspection."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from storage_existing import read_existing
from storage_guard import read_identity


def command(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=30).stdout.strip()


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    if os.geteuid() != 0:
        raise SystemExit('Requires disposable VM root in a private mount namespace')
    root = Path(tempfile.mkdtemp(prefix='elderbrain-inspection-', dir='/tmp'))
    disk = root / 'data.btrfs'
    with disk.open('xb') as stream:
        stream.truncate(256 * 1024**2)
    command('mkfs.btrfs', str(disk))
    device = command('losetup', '--find', '--show', str(disk))
    mounted = False
    target = root / 'mounted'
    target.mkdir()
    try:
        command('mount', '-t', 'btrfs', device, str(target))
        mounted = True
        uuid = command('findmnt', '-n', '-o', 'UUID', '--mountpoint', str(target))
        identity = dict(product='mindflayer-elderbrain', layout_version=1,
                        data_uuid=uuid, disk_serial='fixture-disk',
                        appliance_id='fb7e5cae-d530-4a1b-9138-322ad8fa48d1')
        marker = target / '.elderbrain-volume.json'
        marker.write_text(json.dumps(identity))
        marker.chmod(0o600)
        (target / 'user-fixture').write_text('must remain unchanged')
        command('umount', str(target))
        mounted = False
        before = digest(disk)
        inspected = read_existing(device, uuid, read_identity=read_identity,
                                  temporary_root=str(root))
        assert inspected == identity
        assert digest(disk) == before, 'Read-only inspection modified the filesystem image'
        try:
            read_existing(device, 'wrong-uuid', read_identity=read_identity, temporary_root=str(root))
        except ValueError:
            pass
        else:
            raise AssertionError('Wrong UUID was accepted')
        assert not list(root.glob('elderbrain-data-inspect-*')), 'Inspection mountpoint leaked'
        print(f'PASS: real Btrfs identity inspection, byte-for-byte unchanged image, wrong UUID rejected; {root}')
    finally:
        if mounted:
            command('umount', str(target))
        command('losetup', '--detach', device)


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as error:
        print(error.stderr)
        raise
