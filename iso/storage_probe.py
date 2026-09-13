"""Read-only installer inventory. Never selects, mounts, or modifies a disk."""

import json
import subprocess


COLUMNS = 'PATH,TYPE,SIZE,MODEL,SERIAL,RM,RO,PTTYPE,PARTN,PARTTYPE,FSTYPE,UUID,MOUNTPOINTS'
PARTITION_FLAGS = {
    '21686148-6449-6e6f-744e-656564454649': 'bios_grub',
    'c12a7328-f81f-11d2-ba4b-00a0c93ec93b': 'boot',
    '0fc63daf-8483-4772-8e79-3d69d8477de4': None,
}


def _busy(node):
    # Missing mount information is unsafe, not equivalent to an empty list.
    mounts = node.get('mountpoints')
    if not isinstance(mounts, list) or any(mounts):
        return True
    children = node.get('children', [])
    if not isinstance(children, list):
        return True
    return any(child.get('type') != 'part' or _busy(child) for child in children)


def normalize(document):
    """Normalize lsblk --tree output; refuse a flattened or malformed probe.

    Direct partitions with no holders are the only supported disk children.
    Mounted descendants, active swap, and dm/RAID holders make a disk busy.
    Unknown GPT partition types remain explicit so preserve cannot accept them.
    """
    nodes = document.get('blockdevices')
    if not isinstance(nodes, list):
        raise ValueError('Missing block-device inventory')
    if any(node.get('type') == 'part' for node in nodes):
        raise ValueError('Inventory must retain disk/partition relationships')
    disks = []
    for node in nodes:
        if node.get('type') != 'disk':
            continue
        children = node.get('children', [])
        if not isinstance(children, list):
            raise ValueError('Malformed disk children')
        partitions = []
        for child in children:
            if child.get('type') != 'part':
                continue
            kind = child.get('parttype')
            flag = PARTITION_FLAGS.get(str(kind).lower(), 'unsupported')
            partitions.append({
                'path': child.get('path'), 'number': child.get('partn'),
                'size': child.get('size'), 'flag': flag,
                'fstype': child.get('fstype'), 'uuid': child.get('uuid'),
            })
        disks.append({
            'path': node.get('path'), 'model': node.get('model'),
            'serial': node.get('serial'),
            'size': node.get('size'), 'type': 'disk',
            'removable': node.get('rm'), 'read_only': node.get('ro'),
            'in_use': _busy(node), 'ptable': node.get('pttype'),
            'partitions': partitions,
        })
    return disks


def probe(run=subprocess.run):
    run(['udevadm', 'settle', '--timeout=15'], check=True, capture_output=True,
        text=True, timeout=20)
    result = run(['lsblk', '--json', '--bytes', '--paths', '--tree',
                  '--output', COLUMNS], check=True, capture_output=True,
                 text=True, timeout=20)
    return normalize(json.loads(result.stdout))


if __name__ == '__main__':
    print(json.dumps(probe(), indent=2))
