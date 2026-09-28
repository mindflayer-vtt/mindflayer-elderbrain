"""Add an appliance IP to its existing setup certificate without rotating trust."""
import fcntl
import ipaddress
import os
from pathlib import Path
import pwd
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


def migrate_layout(directory='/var/lib/mindflayer-elderbrain/traefik'):
    """Move legacy dynamic YAML into its atomically watched parent directory."""
    root = Path(directory)
    dynamic = root / 'dynamic'
    if dynamic.exists() or dynamic.is_symlink():
        info = dynamic.lstat()
        if (dynamic.resolve() != dynamic or not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.geteuid() or info.st_mode & 0o022):
            raise ValueError('Unsafe Traefik dynamic configuration directory')
    else:
        dynamic.mkdir(mode=0o700)
    target = dynamic / 'admin-tls.yaml'
    if target.exists() or target.is_symlink():
        return False
    legacy = root / 'admin-tls.yaml'
    info = legacy.lstat()
    if (legacy.resolve() != legacy or not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid() or info.st_mode & 0o022
            or info.st_size > 65536):
        raise ValueError('Unsafe legacy administration TLS routing configuration')
    data = legacy.read_bytes().replace(b'/etc/traefik/dynamic/tls/', b'/etc/traefik/tls/')
    descriptor, temporary = tempfile.mkstemp(prefix='.tls-config-', dir=dynamic)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        sync = os.open(dynamic, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(sync)
        finally:
            os.close(sync)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return True


def validate_layout(directory='/var/lib/mindflayer-elderbrain/traefik',
                    ca_directory='/var/lib/mindflayer-elderbrain/host/admin-ca'):
    root, ca = Path(directory), Path(ca_directory)
    tls, dynamic = root / 'tls', root / 'dynamic'
    for path in (root, tls, dynamic, ca):
        info = path.lstat()
        if (path.resolve() != path or not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.geteuid() or info.st_mode & 0o022):
            raise ValueError('Unsafe administration TLS directory')
    if (tls / 'ca.key').exists() or (tls / 'ca.key').is_symlink():
        raise ValueError('CA signing key must not be present in served TLS state')
    config = dynamic / 'admin-tls.yaml'
    info = config.lstat()
    if (config.resolve() != config or not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid() or info.st_mode & 0o022):
        raise ValueError('Unsafe administration TLS routing configuration')
    for path, private in ((ca / 'ca.key', True), (ca / 'ca.crt', False),
                          (tls / 'admin.key', True), (tls / 'admin.crt', False),
                          (tls / 'ca.crt', False)):
        info = path.lstat()
        if (path.resolve() != path or not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid() or info.st_mode & (0o077 if private else 0o022)):
            raise ValueError('Unsafe administration TLS material')
    trust = ca / 'trust-root.crt' if (ca / 'trust-root.crt').exists() else ca / 'ca.crt'
    if trust != ca / 'ca.crt':
        info = trust.lstat()
        if (trust.resolve() != trust or not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid() or info.st_mode & 0o022):
            raise ValueError('Unsafe administration trust root')
    if trust.read_bytes() != (tls / 'ca.crt').read_bytes():
        raise ValueError('Served CA certificate differs from signing authority')
    openssl(['verify', '-CAfile', trust, '-untrusted', ca / 'ca.crt', tls / 'admin.crt'])
    ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(tls / 'admin.crt', tls / 'admin.key')
    certificate_key = openssl(['x509', '-in', ca / 'ca.crt', '-pubkey', '-noout'])
    signing_key = openssl(['pkey', '-in', ca / 'ca.key', '-pubout'])
    if certificate_key != signing_key:
        raise ValueError('Administration CA certificate and key differ')
    return {'state': 'valid'}


def domain_names(domain):
    from domain_routes import validate_domain
    domain = validate_domain(domain)
    return 'elderbrain.' + domain, [f'DNS:{name}.{domain}' for name in ('elderbrain', 'foundry', 'mindflayer')]


def ensure_names(required, directory='/var/lib/mindflayer-elderbrain/traefik',
                 ca_directory='/var/lib/mindflayer-elderbrain/host/admin-ca', *, common_name=None):
    normalized = []
    for entry in required:
        if entry.startswith('DNS:'):
            if not re.fullmatch(r'DNS:[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,251}[A-Za-z0-9])?', entry):
                raise ValueError('Invalid certificate DNS name')
        elif entry.startswith('IP:'):
            entry = 'IP:' + str(ipaddress.ip_address(entry[3:]))
        else:
            raise ValueError('Invalid certificate alternative name')
        normalized.append(entry)
    required = list(dict.fromkeys(normalized))
    if common_name is not None and (not isinstance(common_name, str)
                                    or not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?', common_name)):
        raise ValueError('Invalid certificate common name')
    root = Path(directory)
    ca = Path(ca_directory)
    tls = root / 'tls'
    certificate, key = tls / 'admin.crt', tls / 'admin.key'
    dynamic = root / 'dynamic/admin-tls.yaml'
    with open(tls / '.refresh.lock', 'a') as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        validate_layout(root, ca)
        original_config = dynamic.read_bytes()
        original_certificate = certificate.read_bytes()
        existing = names(certificate)
        subject = openssl(['x509', '-in', certificate, '-noout', '-subject', '-nameopt', 'RFC2253']).decode().strip()
        changed = any(entry not in existing for entry in required) or (
            common_name is not None and subject != 'subject=CN=' + common_name)
        if changed:
            trust = ca / 'trust-root.crt' if (ca / 'trust-root.crt').exists() else ca / 'ca.crt'
            openssl(['verify', '-CAfile', trust, '-untrusted', ca / 'ca.crt', certificate])
            with tempfile.TemporaryDirectory(prefix='.refresh-', dir=tls) as temporary:
                stage = Path(temporary)
                if common_name is None:
                    openssl(['x509', '-x509toreq', '-in', certificate, '-signkey', key, '-out', stage / 'request.pem'])
                else:
                    openssl(['req', '-new', '-key', key, '-subj', '/CN=' + common_name,
                             '-out', stage / 'request.pem'])
                updated = existing + [entry for entry in required if entry not in existing]
                (stage / 'extensions').write_text('subjectAltName=' + ','.join(updated)
                                                + '\nextendedKeyUsage=serverAuth\nbasicConstraints=critical,CA:FALSE\n')
                openssl(['x509', '-req', '-in', stage / 'request.pem', '-CA', ca / 'ca.crt', '-CAkey', ca / 'ca.key',
                         '-set_serial', '0x' + secrets.token_hex(16), '-days', '825', '-extfile', stage / 'extensions',
                         '-out', stage / 'certificate.pem'])
                for entry in required:
                    verification = ['-verify_ip', entry[3:]] if entry.startswith('IP:') else ['-verify_hostname', entry[4:]]
                    openssl(['verify', '-CAfile', trust, '-untrusted', ca / 'ca.crt', *verification, stage / 'certificate.pem'])
                if trust != ca / 'ca.crt':
                    with open(stage / 'certificate.pem', 'ab') as chain:
                        chain.write((ca / 'ca.crt').read_bytes())
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


def install_authority(certificate, private_key, trust_root,
                      directory='/var/lib/mindflayer-elderbrain/traefik',
                      ca_directory='/var/lib/mindflayer-elderbrain/host/admin-ca', *, domain, publish_trust=True):
    """Explicitly rotate the signing CA and root after validating a replacement chain."""
    values = (certificate, private_key, trust_root)
    if any(not isinstance(value, str) or not value.startswith('-----BEGIN ') or len(value) > 16384 for value in values):
        raise ValueError('Expected PEM signing certificate, private key and trust root')
    root, ca = Path(directory), Path(ca_directory)
    tls, dynamic = root / 'tls', root / 'dynamic/admin-tls.yaml'
    common_name, required_names = domain_names(domain)
    with open(tls / '.refresh.lock', 'a') as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        validate_layout(root, ca)
        original_names = list(dict.fromkeys([*names(tls / 'admin.crt'), *required_names]))
        with tempfile.TemporaryDirectory(prefix='.authority-', dir=ca) as temporary:
            stage = Path(temporary)
            for name, value in (('ca.crt', certificate), ('ca.key', private_key), ('trust-root.crt', trust_root)):
                path = stage / name
                path.write_text(value)
                path.chmod(0o600)
            if openssl(['x509', '-in', stage / 'ca.crt', '-pubkey', '-noout']) != openssl(['pkey', '-in', stage / 'ca.key', '-pubout']):
                raise ValueError('Signing certificate and key do not match')
            # The root must be a real trust anchor, not an arbitrary supplied leaf.
            openssl(['verify', '-CAfile', stage / 'trust-root.crt', stage / 'trust-root.crt'])
            openssl(['verify', '-CAfile', stage / 'trust-root.crt', '-untrusted', stage / 'ca.crt', stage / 'ca.crt'])
            openssl(['req', '-new', '-key', tls / 'admin.key', '-subj', '/CN=' + common_name,
                     '-out', stage / 'request.pem'])
            (stage / 'extensions').write_text('subjectAltName=' + ','.join(original_names)
                                              + '\nextendedKeyUsage=serverAuth\nbasicConstraints=critical,CA:FALSE\n')
            openssl(['x509', '-req', '-in', stage / 'request.pem', '-CA', stage / 'ca.crt', '-CAkey', stage / 'ca.key',
                     '-set_serial', '0x' + secrets.token_hex(16), '-days', '825', '-extfile', stage / 'extensions',
                     '-out', stage / 'admin.crt'])
            for entry in original_names:
                verification = ['-verify_ip', entry[3:]] if entry.startswith('IP:') else ['-verify_hostname', entry[4:]]
                openssl(['verify', '-CAfile', stage / 'trust-root.crt', '-untrusted', stage / 'ca.crt',
                         *verification, stage / 'admin.crt'])
            if (stage / 'ca.crt').read_bytes() != (stage / 'trust-root.crt').read_bytes():
                with open(stage / 'admin.crt', 'ab') as chain:
                    chain.write((stage / 'ca.crt').read_bytes())
            ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(stage / 'admin.crt', tls / 'admin.key')
            targets = {ca / 'ca.crt': stage / 'ca.crt', ca / 'ca.key': stage / 'ca.key',
                       ca / 'trust-root.crt': stage / 'trust-root.crt', tls / 'ca.crt': stage / 'trust-root.crt',
                       tls / 'admin.crt': stage / 'admin.crt'}
            old = {path: path.read_bytes() if path.exists() else None for path in targets}
            trust_file = Path('/usr/local/share/ca-certificates/elderbrain-admin.crt')
            previous_trust = trust_file.read_bytes() if publish_trust and trust_file.exists() else None
            try:
                for path, source in targets.items():
                    if old[path] is None:
                        path.touch(mode=0o600 if path.name.endswith('.key') else 0o644)
                    replace(path, source.read_bytes())
                validate_layout(root, ca)
                if publish_trust:
                    if not trust_file.exists():
                        trust_file.touch(mode=0o644)
                    replace(trust_file, (stage / 'trust-root.crt').read_bytes())
                    subprocess.run(['update-ca-certificates'], check=True, timeout=60, capture_output=True)
                    kiosk = pwd.getpwnam('elderbrain-kiosk')
                    database = f'sql:{kiosk.pw_dir}/.pki/nssdb'
                    subprocess.run(['runuser', '-u', 'elderbrain-kiosk', '--', 'certutil', '-D',
                                    '-n', 'elderbrain-admin', '-d', database], timeout=15, capture_output=True)
                    subprocess.run(['runuser', '-u', 'elderbrain-kiosk', '--', 'certutil', '-A',
                                    '-n', 'elderbrain-admin', '-t', 'C,,', '-i', str(trust_file), '-d', database],
                                   check=True, timeout=15, capture_output=True)
                replace(dynamic, dynamic.read_bytes())
            except Exception:
                for path, data in old.items():
                    if data is None:
                        path.unlink(missing_ok=True)
                    else:
                        replace(path, data)
                if publish_trust:
                    if previous_trust is None:
                        trust_file.unlink(missing_ok=True)
                    else:
                        replace(trust_file, previous_trust)
                    subprocess.run(['update-ca-certificates'], timeout=60, capture_output=True)
                    if previous_trust is not None:
                        try:
                            kiosk = pwd.getpwnam('elderbrain-kiosk')
                            database = f'sql:{kiosk.pw_dir}/.pki/nssdb'
                            subprocess.run(['runuser', '-u', 'elderbrain-kiosk', '--', 'certutil', '-D',
                                            '-n', 'elderbrain-admin', '-d', database], timeout=15, capture_output=True)
                            subprocess.run(['runuser', '-u', 'elderbrain-kiosk', '--', 'certutil', '-A',
                                            '-n', 'elderbrain-admin', '-t', 'C,,', '-i', str(trust_file), '-d', database],
                                           check=True, timeout=15, capture_output=True)
                        except (OSError, subprocess.SubprocessError, KeyError):
                            pass
                raise
    return {'state': 'installed', 'subject': openssl(['x509', '-in', ca / 'ca.crt', '-noout', '-subject']).decode().strip()}


def ensure_address(address, directory='/var/lib/mindflayer-elderbrain/traefik',
                   ca_directory='/var/lib/mindflayer-elderbrain/host/admin-ca'):
    return ensure_names(['IP:' + unicast(address)], directory, ca_directory)


def ensure_domain(domain, directory='/var/lib/mindflayer-elderbrain/traefik',
                  ca_directory='/var/lib/mindflayer-elderbrain/host/admin-ca'):
    common_name, required = domain_names(domain)
    return ensure_names(required, directory, ca_directory, common_name=common_name)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('validate', 'migrate', 'domain'))
    parser.add_argument('--domain')
    parser.add_argument('--directory', default='/var/lib/mindflayer-elderbrain/traefik')
    parser.add_argument('--ca-directory', default='/var/lib/mindflayer-elderbrain/host/admin-ca')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('must run as root')
    if args.action == 'migrate':
        migrate_layout(args.directory)
    elif args.action == 'domain':
        if not args.domain:
            parser.error('--domain is required for the domain action')
        ensure_domain(args.domain, args.directory, args.ca_directory)
    else:
        validate_layout(args.directory, args.ca_directory)
