#!/usr/bin/env python3
"""Enforce the immutable production installation host-target boundary."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# These values describe already-installed 0.1.0 production media. Updating them
# does not migrate existing appliances and must not be done for an ordinary
# online release.
BASELINE_HOST_FILES = 119
BASELINE_HOST_MAPPING_SHA256 = (
    '23f0d02a83d199de8bf707752d9473dc5b2d3b2f1b1ea529d78d69c026264f2c')


def load_host_builder():
    spec = importlib.util.spec_from_file_location('build_host', ROOT / 'release/build-host.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def identity(inventory_file):
    entries = load_host_builder().entries(inventory_file)
    paths = {entry['path']: entry['mode'] for entry in entries}
    paths['runtime/VERSION'] = 0o644
    encoded = json.dumps(
        paths, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
    return {'format': 1, 'files': len(paths), 'sha256': hashlib.sha256(encoded).hexdigest()}


def require_baseline(metadata_file, inventory_file):
    expected = {'format': 1, 'files': BASELINE_HOST_FILES,
                'sha256': BASELINE_HOST_MAPPING_SHA256}
    metadata = json.loads(Path(metadata_file).read_text())
    if metadata != expected:
        raise ValueError('Production host-inventory metadata differs from installed 0.1.0 media')
    actual = identity(inventory_file)
    if actual != expected:
        raise ValueError('Online host target inventory differs from installed 0.1.0 media')
    return actual


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', type=Path,
                        default=ROOT / 'config/releases/production-host-inventory.json')
    parser.add_argument('--inventory', type=Path, default=ROOT / 'release/host-files.json')
    args = parser.parse_args()
    try:
        accepted = require_baseline(args.metadata, args.inventory)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(f'Accepted immutable production host inventory: '
          f'{accepted["files"]} files, {accepted["sha256"]}')
