#!/usr/bin/env python3
"""Sign already-built, independently validated production release inputs."""
import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'appliance/lib'))
from appliance_release import verify
from release_staging import stage

import importlib.util
spec = importlib.util.spec_from_file_location('elderbrain_prepared_inputs', ROOT / 'release/prepared-inputs.py')
prepared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepared)
spec = importlib.util.spec_from_file_location('elderbrain_build_host', ROOT / 'release/build-host.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


def sign(inputs, output, signing_key, public_key, source, commit, tree, version, sequence):
    _, metadata = prepared.verify(inputs, source, commit, tree, version, sequence)
    key_info = Path(signing_key).lstat()
    if not stat.S_ISREG(key_info.st_mode) or key_info.st_mode & 0o077 or key_info.st_uid != os.geteuid():
        raise ValueError('Signing key must be a private regular file owned by the caller')
    public = Path(public_key).read_bytes()
    if not 0 < len(public) <= 16384:
        raise ValueError('Invalid independently supplied public key')
    output = Path(output)
    output.mkdir(mode=0o700)
    paths = {entry['path']: entry['mode'] for entry in host.entries(Path(source) / 'release/host-files.json')}
    paths['runtime/VERSION'] = 0o644
    with tempfile.TemporaryDirectory(prefix='.sign-', dir=output) as temporary:
        work = Path(temporary)
        manifest = work / 'manifest.json'
        manifest.write_bytes((prepared.canonical(metadata) + b'\n'))
        signature = work / 'manifest.sig'
        subprocess.run(['openssl', 'dgst', '-sha256', '-sign', str(signing_key),
                        '-out', str(signature), str(manifest)], check=True,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=10)
        checked = verify(manifest.read_bytes(), signature.read_bytes(), public)
        host_artifact = Path(inputs) / 'elderbrain-host.tar.zst'
        dependency_artifact = Path(inputs) / 'elderbrain-dependencies.tar.zst'
        with stage(host_artifact, manifest.read_bytes(), signature.read_bytes(), public,
                   paths, parent=work) as (release, tree_root):
            if release != checked or (tree_root / 'runtime/VERSION').read_text() != version + '\n':
                raise ValueError('Prepared host archive does not match the signed release')
        with stage(dependency_artifact, manifest.read_bytes(), signature.read_bytes(),
                   public, parent=work, component='dependencies'):
            pass
        for source_path, name in ((host_artifact, 'elderbrain-host.tar.zst'),
                                  (dependency_artifact, 'elderbrain-dependencies.tar.zst'),
                                  (signature, 'manifest.sig'), (manifest, 'manifest.json')):
            os.link(source_path, output / name)
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--source-tree', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--sequence', required=True, type=int)
    parser.add_argument('--signing-key', required=True, type=Path)
    parser.add_argument('--public-key', required=True, type=Path)
    parser.add_argument('--inputs', required=True, type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    value = sign(args.inputs, args.output, args.signing_key, args.public_key,
                 args.source, args.source_commit, args.source_tree, args.version, args.sequence)
    print(json.dumps({'state': 'signed', 'version': value['version'],
                      'releaseSequence': value['releaseSequence']}, sort_keys=True))
