"""Add an appliance IP to its existing setup certificate without rotating trust."""
import fcntl
import ipaddress
import os
from pathlib import Path
import re
import secrets
import ssl
import stat
import subprocess
import tempfile

from network_config import unicast


def openssl(args):
    result = subprocess.run(['openssl', *map(str, args)], capture_output=True, timeout=20)
    if result.returncode:
        raise ValueError('Unable to refresh appliance setup TLS')
    return result.stdout


def names(certificate):
    text = openssl(['x509', '-in', certificate, '-noout', '-ext', 'subjectAltName']).decode()
    if not text.startswith('X509v3 Subject Alternative Name:'):
        raise ValueError('Setup certificate has no supported names')
    result = []
    for entry in text.split('\n', 1)[1].strip().split(','):
        entry = entry.strip()
        if entry.startswith('DNS:') and re.fullmatch(r'[A-Za-z0-9*_.-]{1,253}', entry[4:]):
            result.append(entry)
        elif entry.startswith('IP Address:'):
            result.append('IP:' + str(ipaddress.ip_address(entry.removeprefix('IP Address:'))))
        else:
            raise ValueError('Setup certificate has unsupported alternative names')
    return list(dict.fromkeys(result))


def replace(path, data):
    info = path.stat()
    temporary = path.parent / ('.tls-' + secrets.token_hex(16))
    try:
        with open(temporary, 'xb') as stream:
            os.fchmod(stream.fileno(), info.st_mode & 0o777)
            if os.geteuid() == 0:
                os.fchown(stream.fileno(), info.st_uid, info.st_gid)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def validate_layout(directory='/var/lib/mindflayer-elderbrain/traefik',
                    ca_directory='/var/lib/mindflayer-elderbrain/host/admin-ca'):
    root, ca = Path(directory), Path(ca_directory)
    tls = root / 'tls'
    for path in (root, tls, ca):
        info = path.lstat()
        if (path.resolve() != path or not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.geteuid() or info.st_mode & 0o022):
            raise ValueError('Unsafe administration TLS directory')
    if (tls / 'ca.key').exists() or (tls / 'ca.key').is_symlink():
        raise ValueError('CA signing key must not be present in served TLS state')
    for path, private in ((ca / 'ca.key', True), (ca / 'ca.crt', False),
                          (tls / 'admin.key', True), (tls / 'admin.crt', False),
                          (tls / 'ca.crt', False)):
        info = path.lstat()
        if (path.resolve() != path or not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid() or info.st_mode & (0o077 if private else 0o022)):
            raise ValueError('Unsafe administration TLS material')
    if (ca / 'ca.crt').read_bytes() != (tls / 'ca.crt').read_bytes():
        raise ValueError('Served CA certificate differs from signing authority')
    openssl(['verify', '-CAfile', ca / 'ca.crt', tls / 'admin.crt'])
    ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(tls / 'admin.crt', tls / 'admin.key')
    certificate_key = openssl(['x509', '-in', ca / 'ca.crt', '-pubkey', '-noout'])
    signing_key = openssl(['pkey', '-in', ca / 'ca.key', '-pubout'])
    if certificate_key != signing_key:
        raise ValueError('Administration CA certificate and key differ')
    return {'state': 'valid'}


def ensure_address(address, directory='/var/lib/mindflayer-elderbrain/traefik',
                   ca_directory='/var/lib/mindflayer-elderbrain/host/admin-ca'):
    address = unicast(address)
    root = Path(directory)
    ca = Path(ca_directory)
    tls = root / 'tls'
    certificate, key = tls / 'admin.crt', tls / 'admin.key'
    dynamic = root / 'admin-tls.yaml'
    with open(tls / '.refresh.lock', 'a') as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        validate_layout(root, ca)
        original_config = dynamic.read_bytes()
        original_certificate = certificate.read_bytes()
        existing = names(certificate)
        changed = 'IP:' + address not in existing
        if changed:
            openssl(['verify', '-CAfile', ca / 'ca.crt', certificate])
            with tempfile.TemporaryDirectory(prefix='.refresh-', dir=tls) as temporary:
                stage = Path(temporary)
                openssl(['x509', '-x509toreq', '-in', certificate, '-signkey', key, '-out', stage / 'request.pem'])
                (stage / 'extensions').write_text('subjectAltName=' + ','.join(existing + ['IP:' + address])
                                                + '\nextendedKeyUsage=serverAuth\nbasicConstraints=critical,CA:FALSE\n')
                openssl(['x509', '-req', '-in', stage / 'request.pem', '-CA', ca / 'ca.crt', '-CAkey', ca / 'ca.key',
                         '-set_serial', '0x' + secrets.token_hex(16), '-days', '825', '-extfile', stage / 'extensions',
                         '-out', stage / 'certificate.pem'])
                openssl(['verify', '-CAfile', ca / 'ca.crt', '-verify_ip', address, stage / 'certificate.pem'])
                ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(stage / 'certificate.pem', key)
                if certificate.read_bytes() != original_certificate or dynamic.read_bytes() != original_config:
                    raise ValueError('TLS configuration changed during refresh')
                replace(certificate, (stage / 'certificate.pem').read_bytes())
        # Re-publish even on retry after an interrupted notification. Do not alter
        # any routing or TLS settings: only trigger the existing file watcher.
        if dynamic.read_bytes() != original_config:
            raise ValueError('TLS configuration changed during refresh')
        replace(dynamic, original_config)
        return changed


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('validate',))
    parser.add_argument('--directory', default='/var/lib/mindflayer-elderbrain/traefik')
    parser.add_argument('--ca-directory', default='/var/lib/mindflayer-elderbrain/host/admin-ca')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('must run as root')
    validate_layout(args.directory, args.ca_directory)
