#!/usr/bin/env python3
"""QEMU-only real signed dependency installation; leaves isolated test evidence."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'appliance/lib'))
from release_dependencies import install


def main():
    serial = subprocess.check_output(['lsblk', '-dn', '-o', 'SERIAL', '/dev/vda'], text=True).strip()
    if os.geteuid() != 0 or serial != 'elderbrain-vm-test':
        raise SystemExit('This qualification requires the disposable Elderbrain QEMU guest')
    dependency_inputs = Path(sys.argv[1]).resolve()
    evidence = Path(tempfile.mkdtemp(prefix='elderbrain-signed-deps-', dir='/root'))
    print('Evidence: ' + str(evidence), flush=True)
    spec = importlib.util.spec_from_file_location('assemble', ROOT / 'release/assemble.py')
    assembler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(assembler)
    private, public = evidence / 'test-private.pem', evidence / 'test-public.pem'
    subprocess.run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048',
                    '-out', str(private)], check=True, capture_output=True)
    private.chmod(0o600)
    subprocess.run(['openssl', 'pkey', '-in', str(private), '-pubout', '-out', str(public)],
                   check=True, capture_output=True)
    # These images are deliberately not fetched or qualified in this test.
    image = 'example.test/offline-test@sha256:' + 'a' * 64
    metadata = {'format': 2, 'kind': 'mindflayer-elderbrain-release', 'version': '0.0.0', 'recoveryApi': 1,
        'platform': {'os': 'ubuntu', 'release': '26.04', 'architecture': 'amd64'},
        'host': {'version': '0.0.0', 'apiVersion': 1},
        'setup': {'version': '0.0.0', 'image': image, 'hostApi': {'min': 1, 'max': 1}},
        'images': {name: image for name in ('traefik', 'mindflayer-server', 'foundry')},
        'configurationSchema': 1, 'notes': 'Disposable VM dependency qualification only', 'downtimeSeconds': 0}
    bundle = evidence / 'bundle'
    assembler.assemble(metadata, ROOT, ROOT / 'release/host-files.json', bundle, private, public,
                       dependency_directory=dependency_inputs)
    destination = evidence / 'installed'
    destination.mkdir(mode=0o700)
    paths = {entry['path']: entry['mode'] for entry in assembler.host.entries(ROOT / 'release/host-files.json')}
    paths['runtime/VERSION'] = 0o644
    receipt = install(bundle / 'elderbrain-host.tar.zst', bundle / 'elderbrain-dependencies.tar.zst',
        (bundle / 'manifest.json').read_bytes(), (bundle / 'manifest.sig').read_bytes(), public.read_bytes(),
        paths, directory=destination, configuration_schema=1)
    assert receipt['dependenciesPrepared'] and not receipt['activationReady']
    # Check the console entrypoint still works after all private staging is gone.
    subprocess.run(['unshare', '--net', '--', str(destination / '0.0.0/borgmatic-venv/bin/borgmatic'),
                    '--version'], check=True)
    print('PASS: signed archives verified, offline dependencies installed at stable prefixes; no live activation')


if __name__ == '__main__':
    main()
