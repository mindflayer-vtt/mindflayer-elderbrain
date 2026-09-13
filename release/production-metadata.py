#!/usr/bin/env python3
"""Create reviewed production metadata for the signed release assembler."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'appliance/lib'))
from appliance_release import IMAGE, VERSION, number, pattern


def environment(path):
    selected = {}
    required = {'TRAEFIK_IMAGE', 'MINDFLAYER_SERVER_IMAGE', 'FOUNDRY_IMAGE'}
    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        name, separator, value = line.partition('=')
        if separator and name in required:
            if name in selected:
                raise ValueError('Duplicate production image setting')
            selected[name] = value
    if set(selected) != required:
        raise ValueError('Missing production image setting')
    for value in selected.values():
        pattern(value, IMAGE)
    return selected


def create(version, sequence, setup_image, notes, images_file):
    pattern(version, VERSION)
    number(sequence, 1, 2 ** 63 - 1)
    pattern(setup_image, IMAGE)
    if not isinstance(notes, str) or not notes.strip() or len(notes) > 16000 or '\0' in notes:
        raise ValueError('Release notes must contain 1-16000 safe characters')
    images = environment(images_file)
    return {
        'format': 2,
        'kind': 'mindflayer-elderbrain-release',
        'version': version,
        'releaseSequence': sequence,
        'recoveryApi': 1,
        'platform': {'os': 'ubuntu', 'release': '26.04', 'architecture': 'amd64'},
        'host': {'version': version, 'apiVersion': 1},
        'setup': {'version': version, 'image': setup_image,
                  'hostApi': {'min': 1, 'max': 1}},
        'images': {
            'traefik': images['TRAEFIK_IMAGE'],
            'mindflayer-server': images['MINDFLAYER_SERVER_IMAGE'],
            'foundry': images['FOUNDRY_IMAGE'],
        },
        'configurationSchema': 1,
        'notes': notes.strip(),
        'downtimeSeconds': 300,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--sequence', required=True, type=int)
    parser.add_argument('--setup-image', required=True)
    parser.add_argument('--notes-file', required=True, type=Path)
    parser.add_argument('--images-file', type=Path, default=ROOT / 'config/defaults/appliance.env')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.notes_file.stat().st_size > 16000:
        parser.error('Release notes exceed limit')
    value = create(args.version, args.sequence, args.setup_image,
                   args.notes_file.read_text(), args.images_file)
    with args.output.open('x') as output:
        json.dump(value, output, sort_keys=True, separators=(',', ':'))
        output.write('\n')
