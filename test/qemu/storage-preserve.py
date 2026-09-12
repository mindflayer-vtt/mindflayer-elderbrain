"""Seed/verify a disposable guest's preserve-reinstall fixture; never print secrets.

Run seed once before reinstall. Copy the emitted private manifest file to the
test host before reinstalling, and provide that saved copy to verify afterward.
This supplements guest-storage.py; it does not itself perform an installation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess

STATE = Path('/var/lib/mindflayer-elderbrain')
SCOPES = ('foundry', 'elderbrain', 'mindflayer', 'firmware', 'traefik', 'backups',
          'browser', 'keypad-installations')


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def fingerprint(path):
    info = path.stat()
    return {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'mode': info.st_mode & 0o777, 'uid': info.st_uid, 'gid': info.st_gid}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('seed', 'verify'))
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    assert command('cat', '/sys/class/dmi/id/product_name').startswith('Standard PC'), 'QEMU only'
    assert command('lsblk', '-dn', '-o', 'SERIAL', '/dev/vda') == 'elderbrain-vm-test', 'Disposable disk only'
    identity = json.loads((STATE / '.elderbrain-volume.json').read_text())
    os_uuid = command('findmnt', '-no', 'UUID', '--mountpoint', '/')
    if args.operation == 'seed':
        assert not args.manifest.exists(), 'Do not overwrite a previous baseline'
        files = [STATE / '.elderbrain-volume.json', STATE / 'traefik/admin-tls.yaml']
        for scope in SCOPES:
            parent = STATE / scope
            assert parent.is_dir() and not parent.is_symlink()
            target = parent / '.preserve-test-fixture'
            with open(target, 'xb') as stream:
                stream.write(secrets.token_bytes(128))
                os.fchmod(stream.fileno(), 0o600)
                os.fchown(stream.fileno(), parent.stat().st_uid, parent.stat().st_gid)
                stream.flush()
                os.fsync(stream.fileno())
            files.append(target)
        # Real host identity and administrator settings, not just test files.
        for scope in ('ssh-server', 'ssh-root', 'ssh-admin', 'netplan', 'runtime'):
            files.extend(path for path in (STATE / 'host' / scope).rglob('*')
                         if path.is_file() and not path.is_symlink())
        for name in ('config.json', 'secrets/foundry-config.json', 'secrets/default-smtp.json'):
            path = STATE / 'elderbrain' / name
            if path.is_file():
                files.append(path)
        manifest = {'identity': identity, 'os_uuid': os_uuid,
                    'files': {str(path.relative_to(STATE)): fingerprint(path) for path in files}}
        with open(args.manifest, 'x') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(manifest, stream)
            stream.flush()
            os.fsync(stream.fileno())
        print('Preserve baseline saved; copy the private manifest to the host before reinstall')
    else:
        manifest = json.loads(args.manifest.read_text())
        assert identity == manifest['identity'], 'Appliance/data identity changed'
        assert os_uuid != manifest['os_uuid'], 'OS was not reformatted by this test'
        for name, expected in manifest['files'].items():
            relative = Path(name)
            assert not relative.is_absolute() and '..' not in relative.parts
            assert fingerprint(STATE / relative) == expected, 'Preserved file changed: ' + name
        print('PASS: OS replaced; data identity, fixture contents, SSH identity and settings preserved')


if __name__ == '__main__':
    main()
