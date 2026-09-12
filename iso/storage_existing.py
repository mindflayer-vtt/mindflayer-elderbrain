"""Read an existing appliance marker without replaying Btrfs writes.

Only called in the installer after explicit disk/UUID selection. This module
never formats, repairs, or recursively removes anything, including on failure.
"""

import json
from pathlib import Path
import re
import stat
import subprocess
import tempfile

READ_OPTIONS = 'ro,rescue=nologreplay,nosuid,nodev,noexec,subvolid=5'


def verify_read_mount(document, target, data_uuid):
    mounts = document.get('filesystems')
    if not isinstance(mounts, list) or len(mounts) != 1:
        raise ValueError('Read-only data inspection mount is missing or ambiguous')
    mount = mounts[0]
    options = set(str(mount.get('options', '')).split(','))
    if (mount.get('target') != str(target) or mount.get('fstype') != 'btrfs'
            or mount.get('fsroot') != '/' or mount.get('uuid') != data_uuid
            or not {'ro', 'nosuid', 'nodev', 'noexec'} <= options
            or 'rw' in options):
        raise ValueError('Unsafe or incorrect data inspection mount')


def read_existing(device, data_uuid, *, read_identity, run=subprocess.run,
                  stat_device=lambda path: Path(path).stat(), temporary_root='/run'):
    """Return validated identity after a private, bounded read-only inspection.

    Caller must first reject busy disks and cloned UUIDs using fresh inventory,
    and re-probe after this function unmounts before accepting a storage plan.
    """
    if not isinstance(device, str) or not re.fullmatch(r'/dev/[A-Za-z0-9_-]+', device):
        raise ValueError('Expected a directly probed block-device path')
    if not stat.S_ISBLK(stat_device(device).st_mode):
        raise ValueError('Inspection target is not a block device')

    def command(arguments):
        return run(arguments, check=True, capture_output=True, text=True, timeout=30)

    # Probe the device directly rather than trusting potentially stale udev
    # filesystem attributes. Reject multi-device Btrfs before attempting mount.
    fields = dict(line.split('=', 1) for line in command(
        ['blkid', '--probe', '--output', 'export', device]).stdout.splitlines() if '=' in line)
    if fields.get('TYPE') != 'btrfs' or fields.get('UUID') != data_uuid:
        raise ValueError('Data filesystem identity changed since selection')
    superblock = command(['btrfs', 'inspect-internal', 'dump-super', device]).stdout
    devices = re.findall(r'^num_devices\s+(\d+)\s*$', superblock, re.MULTILINE)
    if devices != ['1']:
        raise ValueError('Only single-device Btrfs appliance volumes are supported')

    target = Path(tempfile.mkdtemp(prefix='elderbrain-data-inspect-', dir=temporary_root))
    try:
        try:
            command(['mount', '-t', 'btrfs', '-o', READ_OPTIONS, device, str(target)])
        except BaseException:
            # A timed-out mount may have succeeded. Attempt only a normal
            # unmount of our exact private directory, never lazy/forced cleanup.
            run(['umount', str(target)], check=False, capture_output=True,
                text=True, timeout=30)
            raise
        try:
            document = json.loads(command([
                'findmnt', '--json', '--mountpoint', str(target),
                '--output', 'TARGET,FSTYPE,UUID,FSROOT,OPTIONS']).stdout)
            verify_read_mount(document, target, data_uuid)
            return read_identity(target / '.elderbrain-volume.json')
        finally:
            command(['umount', str(target)])
    finally:
        # rmdir cannot traverse/delete mounted user data. If cleanup failed,
        # leave the mountpoint for diagnosis and abort the installer.
        target.rmdir()
