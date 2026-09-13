#!/usr/bin/env python3
"""Enforce the committed and authenticated production sequence floor."""
import argparse
import json
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'appliance/lib'))
from appliance_release import MANIFEST_LIMIT, VERSION, keys, number, pattern, unique, verify

BASELINE_LIMIT = 4096


def bounded(path, limit):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
        raise ValueError('Prior release input exceeds limit')
    return path.read_bytes()


def baseline(path):
    value = json.loads(bounded(path, BASELINE_LIMIT), object_pairs_hook=unique)
    keys(value, 'format version releaseSequence')
    if value['format'] != 1:
        raise ValueError('Unsupported production baseline format')
    pattern(value['version'], VERSION)
    number(value['releaseSequence'], 1, 2 ** 63 - 1)
    return value


def version_tuple(value):
    pattern(value, VERSION)
    return tuple(int(part) for part in value.split('.'))


def authenticated_sequence(manifest, signature, public_key):
    release = verify(manifest, signature, public_key)
    return release['releaseSequence']


def require_new(configured, proposed_version, proposed, latest=None):
    keys(configured, 'format version releaseSequence')
    pattern(configured['version'], VERSION)
    number(configured['releaseSequence'], 1, 2 ** 63 - 1)
    number(proposed, 1, 2 ** 63 - 1)
    if version_tuple(proposed_version) <= version_tuple(configured['version']):
        raise ValueError('Production version must exceed the installation baseline')
    floor = configured['releaseSequence']
    if latest is not None:
        number(latest, 1, 2 ** 63 - 1)
        floor = max(floor, latest)
    if proposed <= floor:
        raise ValueError('Release sequence must exceed the production sequence floor')
    return floor


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True, type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--signature', type=Path)
    parser.add_argument('--public-key', required=True, type=Path)
    parser.add_argument('--version', required=True)
    parser.add_argument('--proposed', required=True, type=int)
    args = parser.parse_args()
    if (args.manifest is None) != (args.signature is None):
        parser.error('Supply both latest-release inputs or neither')
    latest = None
    if args.manifest is not None:
        latest = authenticated_sequence(bounded(args.manifest, MANIFEST_LIMIT),
                                        bounded(args.signature, 1024),
                                        bounded(args.public_key, 16384))
    floor = require_new(baseline(args.baseline), args.version, args.proposed, latest)
    print(f"Accepted sequence {args.proposed} above production floor {floor}")
