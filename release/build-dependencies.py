#!/usr/bin/env python3
"""Build target-platform offline dependency inputs; no live environment install."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys


def requirements(file):
    selected = {}
    for line in Path(file).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)', line)
        if not match:
            raise ValueError('Offline runtime requirements must be exact package pins')
        name = re.sub(r'[-_.]+', '-', match[1]).lower()
        if name in selected:
            raise ValueError('Duplicate offline package pin')
        selected[name] = match[2]
    if not selected:
        raise ValueError('Empty runtime dependency set')
    return selected


def browser_package(file):
    lock = json.loads(Path(file).read_text())
    packages = lock['packages']
    if set(packages) != {'', 'node_modules/playwright-core'}:
        raise ValueError('Review changed browser dependency graph before bundling')
    package = packages['node_modules/playwright-core']
    version, integrity = package['version'], package['integrity']
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version) or not integrity.startswith('sha512-'):
        raise ValueError('Invalid browser dependency lock')
    expected = base64.b64decode(integrity[7:], validate=True)
    if len(expected) != 64:
        raise ValueError('Invalid browser package integrity')
    return version, expected


def build(source, output):
    os_release = platform.freedesktop_os_release()
    if (os_release.get('ID'), os_release.get('VERSION_ID'), platform.machine(), sys.version_info[:2]) != (
            'ubuntu', '26.04', 'x86_64', (3, 14)):
        raise ValueError('Build dependency artifacts on Ubuntu 26.04 amd64 with Python 3.14')
    source, output = Path(source), Path(output)
    locks = [source / 'config/defaults' / (name + '-requirements.txt') for name in ('serial', 'borgmatic')]
    combined = {}
    for file in locks:
        for name, version in requirements(file).items():
            if name in combined and combined[name] != version:
                raise ValueError('Conflicting runtime dependency pins')
            combined[name] = version
    browser_lock = source / 'provisioning/graphics/package-lock.json'
    browser_version, browser_integrity = browser_package(browser_lock)
    output.mkdir(mode=0o700)  # Never overwrite an earlier build/evidence directory.
    wheels, node = output / 'wheels', output / 'node'
    wheels.mkdir(mode=0o700)
    node.mkdir(mode=0o700)
    # Pin every runtime package and do not resolve additional runtime versions.
    # Building source distributions is a release-builder operation, not appliance
    # startup. Build-isolation dependencies may still be fetched by pip here.
    command = [sys.executable, '-m', 'pip', 'wheel', '--no-deps', '--no-cache-dir', '--wheel-dir', str(wheels)]
    for file in locks:
        command += ['-r', str(file)]
    print('Building pinned Python wheels', flush=True)
    subprocess.run(command, check=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=1800)
    print('Packing the locked browser helper dependency', flush=True)
    subprocess.run(['npm', 'pack', 'playwright-core@' + browser_version, '--ignore-scripts',
                    '--pack-destination', str(node)], check=True, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
    node_archive = node / ('playwright-core-' + browser_version + '.tgz')
    if hashlib.sha512(node_archive.read_bytes()).digest() != browser_integrity:
        raise ValueError('Browser dependency differs from the reviewed lock integrity')
    files = {}
    for file in sorted([*wheels.iterdir(), *node.iterdir()]):
        if not file.is_file() or file.is_symlink() or (file.parent == wheels and file.suffix != '.whl'):
            raise ValueError('Unexpected dependency build artifact')
        files[str(file.relative_to(output))] = {'size': file.stat().st_size, 'sha256': hashlib.sha256(file.read_bytes()).hexdigest()}
        with file.open('rb') as stream:
            os.fsync(stream.fileno())
    if len(list(wheels.iterdir())) != len(combined):
        raise ValueError('Offline wheel count differs from reviewed runtime pins')
    receipt = {'format': 1, 'platform': {'os': 'ubuntu', 'release': '26.04', 'architecture': 'amd64'},
               'python': platform.python_version(), 'requirements': combined, 'files': files,
               'inputs': {str(file.relative_to(source)): hashlib.sha256(file.read_bytes()).hexdigest()
                          for file in [*locks, browser_lock]}, 'offlineInstallVerified': False}
    with (output / 'dependencies.json').open('x') as stream:
        json.dump(receipt, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    for directory in (wheels, node, output, output.parent):
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    receipt = build(args.source, args.output)
    print(json.dumps({'state': 'built', 'files': len(receipt['files']), 'offlineInstallVerified': False}))
