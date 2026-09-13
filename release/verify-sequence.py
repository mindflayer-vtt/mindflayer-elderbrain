#!/usr/bin/env python3
"""Verify the current published manifest and require a newer release sequence."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'appliance/lib'))
from appliance_release import MANIFEST_LIMIT, number, verify


def bounded(path, limit):
    path = Path(path)
    if not 0 < path.stat().st_size <= limit:
        raise ValueError('Prior release input exceeds limit')
    return path.read_bytes()


def require_new(previous, proposed):
    number(previous, 1, 2 ** 63 - 1)
    number(proposed, 1, 2 ** 63 - 1)
    if proposed <= previous:
        raise ValueError('Release sequence must exceed the latest published release')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--signature', required=True, type=Path)
    parser.add_argument('--public-key', required=True, type=Path)
    parser.add_argument('--proposed', required=True, type=int)
    args = parser.parse_args()
    release = verify(bounded(args.manifest, MANIFEST_LIMIT),
                     bounded(args.signature, 1024), bounded(args.public_key, 16384))
    require_new(release['releaseSequence'], args.proposed)
    print(f"Accepted sequence {args.proposed} after {release['releaseSequence']}")
