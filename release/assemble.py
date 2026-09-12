#!/usr/bin/env python3
"""Assemble and verify local signed release artifacts; never publish or deploy."""
import argparse
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'appliance/lib'))
from appliance_release import keys, unique, validate
from release_staging import stage

spec = importlib.util.spec_from_file_location('elderbrain_build_host', ROOT / 'release/build-host.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


def assemble(metadata, source, inventory, output, signing_key, public_key):
    release = deepcopy(metadata)
    if not isinstance(release, dict) or not isinstance(release.get('host'), dict):
        raise ValueError('Invalid release metadata')
    keys(release['host'], 'version apiVersion')
    release['host']['artifact'] = {'file': 'elderbrain-host.tar.zst', 'size': 1, 'sha256': '0' * 64}
    validate(release)  # Reject unsupported image/API/schema fields before signing.
    selected = host.entries(inventory)
    paths = {entry['path']: entry['mode'] for entry in selected}
    paths['runtime/VERSION'] = 0o644
    info = Path(signing_key).lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.geteuid():
        raise ValueError('Signing key must be a private regular file owned by the caller')
    public = Path(public_key).read_bytes()
    if not 0 < len(public) <= 16384:
        raise ValueError('Invalid independently supplied public key')
    output = Path(output)
    output.mkdir(mode=0o700)  # Exclusive; preserve all existing output directories.
    descriptor = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    with tempfile.TemporaryDirectory(prefix='.assemble-', dir=output) as temporary:
        work = Path(temporary)
        artifact = work / 'elderbrain-host.tar.zst'
        release['host']['artifact'] = host.build(source, inventory, artifact, release['host']['version'])
        manifest = work / 'manifest.json'
        manifest.write_bytes((json.dumps(validate(release), sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode())
        signature = work / 'manifest.sig'
        subprocess.run(['openssl', 'dgst', '-sha256', '-sign', str(signing_key), '-out', str(signature), str(manifest)],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=10)
        # Verify with the separately supplied pin, not a public key derived from
        # whichever private key happened to be passed to the signing command.
        with stage(artifact, manifest.read_bytes(), signature.read_bytes(), public, paths, parent=work) as (checked, tree):
            if (tree / 'runtime/VERSION').read_text() != checked['host']['version'] + '\n':
                raise ValueError('Packaged host version does not match release metadata')
        # Manifest is the final readiness artifact. Never expose a manifest for
        # failed signing, wrong-key verification or invalid package inventory.
        for name in ('elderbrain-host.tar.zst', 'manifest.sig', 'manifest.json'):
            file = work / name
            with file.open('rb') as stream:
                os.fsync(stream.fileno())
            os.link(file, output / name)
            descriptor = os.open(output, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    return release


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', required=True, type=Path)
    parser.add_argument('--source', type=Path, default=ROOT)
    parser.add_argument('--inventory', type=Path, default=ROOT / 'release/host-files.json')
    parser.add_argument('--signing-key', required=True, type=Path)
    parser.add_argument('--public-key', required=True, type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.metadata.stat().st_size > 65536:
        parser.error('Metadata exceeds size limit')
    metadata = json.loads(args.metadata.read_bytes(), object_pairs_hook=unique)
    release = assemble(metadata, args.source, args.inventory, args.output, args.signing_key, args.public_key)
    print(json.dumps({'version': release['version'], 'host': release['host']['artifact'], 'state': 'assembled'}))
