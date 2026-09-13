#!/usr/bin/env python3
"""Perform only the minimal private-key operation on an approved manifest."""
import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'appliance/lib'))
from appliance_release import unique, validate, verify


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def regular_private(path, description):
    info = Path(path).lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.geteuid():
        raise ValueError(f'{description} must be a private regular file owned by the caller')
    return info


def sign(manifest, signature, signing_key, public_key):
    manifest, signature = Path(manifest), Path(signature)
    expected = {'elderbrain-host.tar.zst', 'elderbrain-dependencies.tar.zst', 'manifest.json'}
    if manifest.name != 'manifest.json' or signature.name != 'manifest.sig':
        raise ValueError('Use the fixed production manifest and signature names')
    if {entry.name for entry in manifest.parent.iterdir()} != expected:
        raise ValueError('Signing directory is not the exact approved pre-sign set')
    info = manifest.lstat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 65536:
        raise ValueError('Invalid approved canonical manifest')
    raw = manifest.read_bytes()
    release = validate(json.loads(raw, object_pairs_hook=unique))
    if canonical(release) + b'\n' != raw:
        raise ValueError('Approved manifest is not canonical')
    regular_private(signing_key, 'Signing key')
    public = Path(public_key).read_bytes()
    if not 0 < len(public) <= 16384 or signature.exists():
        raise ValueError('Invalid signature destination or independently supplied public key')
    subprocess.run(['openssl', 'dgst', '-sha256', '-sign', str(signing_key),
                    '-out', str(signature), str(manifest)], check=True,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=10)
    if not stat.S_ISREG(signature.lstat().st_mode):
        raise ValueError('OpenSSL did not create a regular signature')
    verify(raw, signature.read_bytes(), public)
    return release


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--signature', required=True, type=Path)
    parser.add_argument('--signing-key', required=True, type=Path)
    parser.add_argument('--public-key', required=True, type=Path)
    args = parser.parse_args()
    value = sign(args.manifest, args.signature, args.signing_key, args.public_key)
    print(json.dumps({'state': 'signed', 'version': value['version'],
                      'releaseSequence': value['releaseSequence']}, sort_keys=True))
