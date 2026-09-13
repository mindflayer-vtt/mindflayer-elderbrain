#!/usr/bin/env python3
"""Create and strictly verify unsigned inputs transferred to the signing job."""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'appliance/lib'))
from appliance_release import IMAGE, VERSION, keys, number, pattern, unique, validate, verify_artifact


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


production = module('elderbrain_production_metadata', ROOT / 'release/production-metadata.py')
host = module('elderbrain_build_host', ROOT / 'release/build-host.py')
dependencies = module('elderbrain_pack_dependencies', ROOT / 'release/pack-dependencies.py')

FILES = {
    'release-metadata.json': 65536,
    'release-notes.md': 16001,
    'elderbrain-host.tar.zst': 8 * 1024 ** 3,
    'elderbrain-dependencies.tar.zst': 512 * 1024 ** 2,
}
RECEIPT = 'preparation-receipt.json'
DEPENDENCY_INPUTS = (
    'config/defaults/serial-requirements.txt',
    'config/defaults/borgmatic-requirements.txt',
    'provisioning/graphics/package-lock.json',
)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()


def hash_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def regular(path, limit, *, allow_empty=False):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > limit or (not allow_empty and info.st_size == 0):
        raise ValueError(f'Invalid prepared input: {path.name}')
    return info.st_size


def dependency_input_hashes(source):
    source = Path(source).resolve()
    values = {}
    for name in DEPENDENCY_INPUTS:
        path = source / name
        regular(path, 1024 * 1024)
        values[name] = hash_file(path)
    return values


def source_identity(version, sequence, commit, tree):
    pattern(version, VERSION)
    number(sequence, 1, 2 ** 63 - 1)
    for value in (commit, tree):
        if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{40}', value):
            raise ValueError('Invalid Git source identity')
    core = {'format': 1, 'version': version, 'releaseSequence': sequence,
            'sourceCommit': commit, 'sourceTree': tree, 'inputMode': 'tracked-commit'}
    return digest_bytes(canonical(core))


def dependency_receipt(directory, source):
    path = Path(directory) / 'dependencies.json'
    regular(path, 65536)
    value = json.loads(path.read_bytes(), object_pairs_hook=unique)
    required = {'format', 'platform', 'python', 'requirements', 'files', 'inputs', 'offlineInstallVerified'}
    if not isinstance(value, dict) or set(value) != required or value['format'] != 1:
        raise ValueError('Invalid dependency build receipt schema')
    expected = dependency_input_hashes(source)
    if value['inputs'] != expected:
        raise ValueError('Dependency build inputs differ from the checked-out source')
    return value, digest_bytes(canonical(expected))


def write_exclusive(path, data):
    with Path(path).open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def create(source, dependency_directory, notes_file, output, version, sequence,
           setup_image, commit, tree):
    source, output = Path(source).resolve(), Path(output)
    pattern(setup_image, IMAGE)
    receipt, dependency_inputs_sha256 = dependency_receipt(dependency_directory, source)
    output.mkdir(mode=0o700)
    notes = Path(notes_file).read_text()
    base = production.create(version, sequence, setup_image, notes,
                             source / 'config/defaults/appliance.env')
    host_path = output / 'elderbrain-host.tar.zst'
    base['host']['artifact'] = host.build(source, source / 'release/host-files.json', host_path, version)
    dependency_path = output / 'elderbrain-dependencies.tar.zst'
    base['dependencies'] = dependencies.pack(dependency_directory, dependency_path)
    metadata = validate(base)
    metadata_bytes = canonical(metadata) + b'\n'
    write_exclusive(output / 'release-metadata.json', metadata_bytes)
    normalized_notes = metadata['notes'].encode() + b'\n'
    write_exclusive(output / 'release-notes.md', normalized_notes)
    files = {}
    for name, limit in FILES.items():
        path = output / name
        files[name] = {'size': regular(path, limit), 'sha256': hash_file(path)}
    value = {
        'format': 1,
        'sourceCommit': commit,
        'sourceTree': tree,
        'sourceIdentity': source_identity(version, sequence, commit, tree),
        'version': version,
        'releaseSequence': sequence,
        'setupImage': setup_image,
        'metadataSha256': digest_bytes(metadata_bytes),
        'dependencyInputsSha256': dependency_inputs_sha256,
        'preparedFiles': files,
    }
    write_exclusive(output / RECEIPT, canonical(value) + b'\n')
    return value


def read_receipt(path):
    path = Path(path)
    regular(path, 65536)
    value = json.loads(path.read_bytes(), object_pairs_hook=unique)
    keys(value, 'format sourceCommit sourceTree sourceIdentity version releaseSequence '
                'setupImage metadataSha256 dependencyInputsSha256 preparedFiles')
    if value['format'] != 1:
        raise ValueError('Unsupported preparation receipt format')
    pattern(value['version'], VERSION)
    number(value['releaseSequence'], 1, 2 ** 63 - 1)
    pattern(value['setupImage'], IMAGE)
    for field in ('sourceCommit', 'sourceTree'):
        pattern(value[field], r'[a-f0-9]{40}')
    for field in ('sourceIdentity', 'metadataSha256', 'dependencyInputsSha256'):
        pattern(value[field], r'[a-f0-9]{64}')
    if not isinstance(value['preparedFiles'], dict) or set(value['preparedFiles']) != set(FILES):
        raise ValueError('Unsupported prepared file inventory')
    for name, metadata in value['preparedFiles'].items():
        keys(metadata, 'size sha256')
        number(metadata['size'], 1, FILES[name])
        pattern(metadata['sha256'], r'[a-f0-9]{64}')
    return value


def verify(directory, source, commit, tree, version, sequence):
    directory, source = Path(directory).resolve(), Path(source).resolve()
    actual_names = {entry.name for entry in directory.iterdir()}
    if actual_names != set(FILES) | {RECEIPT}:
        raise ValueError('Prepared transfer has missing or unexpected entries')
    receipt = read_receipt(directory / RECEIPT)
    if (receipt['sourceCommit'], receipt['sourceTree'], receipt['version'], receipt['releaseSequence']) != (
            commit, tree, version, sequence):
        raise ValueError('Prepared release identity differs from this workflow')
    expected_identity = source_identity(version, sequence, commit, tree)
    if receipt['sourceIdentity'] != expected_identity:
        raise ValueError('Prepared source identity mismatch')
    expected_dependency_hash = digest_bytes(canonical(dependency_input_hashes(source)))
    if receipt['dependencyInputsSha256'] != expected_dependency_hash:
        raise ValueError('Prepared dependency inputs differ from this source')
    for name, expected in receipt['preparedFiles'].items():
        path = directory / name
        size = regular(path, FILES[name])
        if size != expected['size'] or hash_file(path) != expected['sha256']:
            raise ValueError(f'Prepared input hash mismatch: {name}')
    metadata_path = directory / 'release-metadata.json'
    metadata_bytes = metadata_path.read_bytes()
    if receipt['metadataSha256'] != digest_bytes(metadata_bytes):
        raise ValueError('Prepared metadata hash mismatch')
    metadata = validate(json.loads(metadata_bytes, object_pairs_hook=unique))
    if canonical(metadata) + b'\n' != metadata_bytes:
        raise ValueError('Prepared metadata is not canonical')
    notes = (directory / 'release-notes.md').read_text()
    expected = production.create(version, sequence, receipt['setupImage'], notes,
                                 source / 'config/defaults/appliance.env')
    expected['host']['artifact'] = deepcopy(metadata['host']['artifact'])
    expected['dependencies'] = deepcopy(metadata['dependencies'])
    if expected != metadata:
        raise ValueError('Prepared metadata differs from independently generated production metadata')
    verify_artifact(directory / 'elderbrain-host.tar.zst', metadata, 'host')
    verify_artifact(directory / 'elderbrain-dependencies.tar.zst', metadata, 'dependencies')
    return receipt, metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='command', required=True)
    create_parser = subparsers.add_parser('create')
    create_parser.add_argument('--source', type=Path, default=ROOT)
    create_parser.add_argument('--dependencies', required=True, type=Path)
    create_parser.add_argument('--notes-file', required=True, type=Path)
    create_parser.add_argument('--version', required=True)
    create_parser.add_argument('--sequence', required=True, type=int)
    create_parser.add_argument('--setup-image', required=True)
    create_parser.add_argument('--source-commit', required=True)
    create_parser.add_argument('--source-tree', required=True)
    create_parser.add_argument('output', type=Path)
    verify_parser = subparsers.add_parser('verify')
    verify_parser.add_argument('--source', type=Path, default=ROOT)
    verify_parser.add_argument('--source-commit', required=True)
    verify_parser.add_argument('--source-tree', required=True)
    verify_parser.add_argument('--version', required=True)
    verify_parser.add_argument('--sequence', required=True, type=int)
    verify_parser.add_argument('--github-output', type=Path)
    verify_parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    if args.command == 'create':
        result = create(args.source, args.dependencies, args.notes_file, args.output,
                        args.version, args.sequence, args.setup_image,
                        args.source_commit, args.source_tree)
    else:
        result, _ = verify(args.directory, args.source, args.source_commit,
                           args.source_tree, args.version, args.sequence)
        if args.github_output:
            with args.github_output.open('a') as stream:
                stream.write('setup-image=' + result['setupImage'] + '\n')
    print(json.dumps(result, sort_keys=True))
