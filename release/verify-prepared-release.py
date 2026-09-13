#!/usr/bin/env python3
"""Deeply approve prepared release bytes against a clean source checkout."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'appliance/lib'))
from release_staging import FILE_LIMIT, stage_verified


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


prepared = module('elderbrain_prepared_inputs', ROOT / 'release/prepared-inputs.py')
host = module('elderbrain_build_host', ROOT / 'release/build-host.py')


def equal_files(left, right):
    while True:
        left_chunk = left.read(1024 * 1024)
        right_chunk = right.read(1024 * 1024)
        if left_chunk != right_chunk:
            return False
        if not left_chunk:
            return True


def compare_host_tree(tree, source, inventory_file, version):
    """Bind every staged host byte to its reviewed clean-checkout source."""
    source = Path(source).resolve()
    entries = host.entries(inventory_file)
    version_file = tree / 'runtime/VERSION'
    if version_file.read_bytes() != (version + '\n').encode():
        raise ValueError('Prepared host runtime/VERSION differs from the requested version')
    for entry in entries:
        source_path = source / entry['source']
        if source_path.resolve() != source_path:
            raise ValueError('Clean checkout host source symlink rejected')
        descriptor = os.open(source_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as clean, (tree / entry['path']).open('rb') as candidate:
            info = os.fstat(clean.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > FILE_LIMIT:
                raise ValueError('Invalid clean checkout host source type or size')
            if not equal_files(clean, candidate):
                raise ValueError(f'Prepared host source differs from clean checkout: {entry["source"]}')


def approve(inputs, output, source, commit, tree, version, sequence):
    """Deeply validate candidate archives and create the fixed pre-sign set."""
    inputs, output, source = Path(inputs).resolve(), Path(output), Path(source).resolve()
    _, metadata = prepared.verify(inputs, source, commit, tree, version, sequence)
    output.mkdir(mode=0o700)
    metadata_bytes = prepared.canonical(metadata) + b'\n'
    manifest = output / 'manifest.json'
    prepared.write_exclusive(manifest, metadata_bytes)
    host_artifact = output / 'elderbrain-host.tar.zst'
    dependency_artifact = output / 'elderbrain-dependencies.tar.zst'
    os.link(inputs / host_artifact.name, host_artifact)
    os.link(inputs / dependency_artifact.name, dependency_artifact)
    selected = host.entries(source / 'release/host-files.json')
    paths = {entry['path']: entry['mode'] for entry in selected}
    paths['runtime/VERSION'] = 0o644
    with tempfile.TemporaryDirectory(prefix='release-approval-') as temporary:
        parent = Path(temporary)
        with stage_verified(host_artifact, metadata, paths, parent=parent) as (_, staged):
            compare_host_tree(staged, source, source / 'release/host-files.json', version)
        with stage_verified(dependency_artifact, metadata, parent=parent,
                            component='dependencies'):
            pass
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--source-tree', required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--sequence', required=True, type=int)
    parser.add_argument('--inputs', required=True, type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    value = approve(args.inputs, args.output, args.source, args.source_commit,
                    args.source_tree, args.version, args.sequence)
    print(json.dumps({'state': 'approved', 'version': value['version'],
                      'releaseSequence': value['releaseSequence']}, sort_keys=True))
