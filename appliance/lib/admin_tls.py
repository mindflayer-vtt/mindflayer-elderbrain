"""Add an appliance IP to its existing setup certificate without rotating trust."""
import fcntl
import ipaddress
import os
from pathlib import Path
import re
import secrets
import ssl
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


def ensure_address(address, directory='/var/lib/mindflayer-elderbrain/traefik'):
    address = unicast(address)
    root = Path(directory)
    tls = root / 'tls'
    certificate, key = tls / 'admin.crt', tls / 'admin.key'
    dynamic = root / 'admin-tls.yaml'
    with open(tls / '.refresh.lock', 'a') as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        original_config = dynamic.read_bytes()
        original_certificate = certificate.read_bytes()
        existing = names(certificate)
        changed = 'IP:' + address not in existing
        if changed:
            openssl(['verify', '-CAfile', tls / 'ca.crt', certificate])
            with tempfile.TemporaryDirectory(prefix='.refresh-', dir=tls) as temporary:
                stage = Path(temporary)
                openssl(['x509', '-x509toreq', '-in', certificate, '-signkey', key, '-out', stage / 'request.pem'])
                (stage / 'extensions').write_text('subjectAltName=' + ','.join(existing + ['IP:' + address])
                                                + '\nextendedKeyUsage=serverAuth\nbasicConstraints=critical,CA:FALSE\n')
                openssl(['x509', '-req', '-in', stage / 'request.pem', '-CA', tls / 'ca.crt', '-CAkey', tls / 'ca.key',
                         '-set_serial', '0x' + secrets.token_hex(16), '-days', '825', '-extfile', stage / 'extensions',
                         '-out', stage / 'certificate.pem'])
                openssl(['verify', '-CAfile', tls / 'ca.crt', '-verify_ip', address, stage / 'certificate.pem'])
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
