#!/usr/bin/env python3
"""Verify the complete fixed production release set with the independent key."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'appliance/lib'))
from appliance_release import verify
from release_staging import stage

import importlib.util
spec = importlib.util.spec_from_file_location('elderbrain_build_host', ROOT / 'release/build-host.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


def check(directory, public_key, source=ROOT):
    directory = Path(directory)
    names = {'elderbrain-host.tar.zst', 'elderbrain-dependencies.tar.zst',
             'manifest.json', 'manifest.sig'}
    if {entry.name for entry in directory.iterdir()} != names:
        raise ValueError('Release directory must contain exactly the four production assets')
    raw, signature, public = ((directory / 'manifest.json').read_bytes(),
                              (directory / 'manifest.sig').read_bytes(),
                              Path(public_key).read_bytes())
    release = verify(raw, signature, public)
    paths = {entry['path']: entry['mode'] for entry in host.entries(Path(source) / 'release/host-files.json')}
    paths['runtime/VERSION'] = 0o644
    with tempfile.TemporaryDirectory(prefix='release-final-verify-') as temporary:
        with stage(directory / 'elderbrain-host.tar.zst', raw, signature, public,
                   paths, parent=Path(temporary)):
            pass
        with stage(directory / 'elderbrain-dependencies.tar.zst', raw, signature,
                   public, parent=Path(temporary), component='dependencies'):
            pass
    return release


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-key', required=True, type=Path)
    parser.add_argument('--source', type=Path, default=ROOT)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    value = check(args.directory, args.public_key, args.source)
    print(json.dumps({'state': 'verified', 'version': value['version'],
                      'releaseSequence': value['releaseSequence']}, sort_keys=True))
