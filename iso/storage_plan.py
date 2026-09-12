"""Pure, fail-closed Curtin storage planning; never probes or modifies a disk.

The installer adapter must supply a freshly probed inventory and, for reinstall,
metadata read from the explicitly selected data filesystem mounted read-only.
No automatic largest-disk selection or legacy-layout migration is permitted.
"""

from uuid import UUID

MIB = 1024**2
GIB = 1024**3
ROOT_SIZE = 48 * GIB
MIN_DATA_SIZE = 24 * GIB
DATA_MOUNT = '/var/lib/mindflayer-elderbrain'
LAYOUT_VERSION = 1


def _uuid(value):
    if not isinstance(value, str):
        raise ValueError('A filesystem UUID is required')
    try:
        parsed = str(UUID(value))
    except (ValueError, AttributeError) as error:
        raise ValueError('Invalid filesystem UUID') from error
    if parsed != value:
        raise ValueError('UUID must use canonical lowercase form')
    return parsed


def plan(inventory, *, mode, serial, erase_confirmed=False,
         data_uuid=None, metadata=None, uefi=True):
    """Return storage config for an explicitly selected, non-removable disk.

    Inventory entries: serial, size (bytes), type, removable, read_only,
    in_use, ptable and partitions. Partition entries: number, size, fstype,
    uuid and flag. Unknown/missing safety facts are rejected.
    """
    if mode not in ('fresh', 'preserve'):
        raise ValueError('Choose fresh or preserve installation explicitly')
    if not isinstance(serial, str) or not serial.strip():
        raise ValueError('An explicit disk serial is required')
    matches = [disk for disk in inventory if disk.get('serial') == serial]
    if len(matches) != 1:
        raise ValueError('Disk serial is missing or ambiguous')
    disk = matches[0]
    if (disk.get('type') != 'disk' or disk.get('removable') is not False
            or disk.get('read_only') is not False or disk.get('in_use') is not False):
        raise ValueError('Target must be an unused, writable, non-removable disk')
    size = disk.get('size')
    if type(size) is not int or size < ROOT_SIZE + MIN_DATA_SIZE + 515 * MIB:
        raise ValueError('Disk is too small for OS and persistent data')
    preserve = mode == 'preserve'
    if not preserve and erase_confirmed is not True:
        raise ValueError('Fresh installation requires explicit disk-erasure confirmation')

    # Both firmware modes use the same GPT layout, permitting later boot-mode
    # changes without moving or resizing the persistent partition.
    partitions = [
        {'number': 1, 'size': MIB, 'flag': 'bios_grub'},
        {'number': 2, 'size': 512 * MIB, 'flag': 'boot'},
        {'number': 3, 'size': ROOT_SIZE},
        {'number': 4, 'size': -1},
    ]
    if preserve:
        data_uuid = _uuid(data_uuid)
        if (not isinstance(metadata, dict)
                or metadata.get('product') != 'mindflayer-elderbrain'
                or type(metadata.get('layout_version')) is not int
                or metadata.get('layout_version') != LAYOUT_VERSION
                or metadata.get('data_uuid') != data_uuid
                or metadata.get('disk_serial') != serial):
            raise ValueError('Persistent filesystem metadata does not match this appliance layout')
        _uuid(metadata.get('appliance_id'))
        existing = disk.get('partitions', [])
        if disk.get('ptable') != 'gpt' or len(existing) != 4:
            raise ValueError('Unsupported partition layout; refusing preserve installation')
        if sorted(p.get('number', 0) for p in existing) != [1, 2, 3, 4]:
            raise ValueError('Unexpected or duplicate partition numbers')
        by_number = {p['number']: p for p in existing}
        for expected in partitions:
            actual = by_number[expected['number']]
            if actual.get('flag') != expected.get('flag'):
                raise ValueError('Partition flags do not match the appliance layout')
            if expected['number'] != 4 and actual.get('size') != expected['size']:
                raise ValueError('Partition sizes do not match the appliance layout')
        data = by_number[4]
        if (type(data.get('size')) is not int or data['size'] < MIN_DATA_SIZE
                or data.get('fstype') != 'btrfs' or data.get('uuid') != data_uuid
                or by_number[2].get('fstype') != 'vfat'
                or by_number[3].get('fstype') != 'ext4'):
            raise ValueError('Existing filesystems do not match the appliance layout')
        # Never use a grow-to-fill size when preserving: Curtin must validate
        # the exact existing geometry, not resize the data partition.
        partitions[3]['size'] = data['size']
        uuid_matches = [p for d in inventory for p in d.get('partitions', [])
                        if p.get('uuid') == data_uuid]
        if len(uuid_matches) != 1:
            raise ValueError('Persistent filesystem UUID is ambiguous')

    target = {'id': 'appliance-disk', 'type': 'disk', 'serial': serial,
              'ptable': 'gpt', 'preserve': preserve, 'grub_device': not uefi}
    if not preserve:
        target['wipe'] = 'superblock-recursive'
    config = [target]
    for partition in partitions:
        number = partition['number']
        action = {'id': f'partition-{number}', 'type': 'partition',
                  'device': 'appliance-disk', 'preserve': preserve, **partition}
        if number == 2 and uefi:
            action['grub_device'] = True
        config.append(action)
    for number, fstype, path in [(2, 'fat32', '/boot/efi'), (3, 'ext4', '/'),
                                 (4, 'btrfs', DATA_MOUNT)]:
        config.append({'id': f'filesystem-{number}', 'type': 'format',
                       'volume': f'partition-{number}', 'fstype': fstype,
                       'preserve': preserve and number in (2, 4)})
        config.append({'id': f'mount-{number}', 'type': 'mount',
                       'device': f'filesystem-{number}', 'path': path,
                       'options': 'defaults'})
    return {'version': 1, 'config': config}
