"""Short-lived network confirmation certificate signed by the appliance CA."""
from pathlib import Path
import secrets
import ssl
import subprocess
import tempfile

from network_config import unicast


def context(address, ca_directory='/var/lib/mindflayer-elderbrain/traefik/tls'):
    address = unicast(address)
    ca = Path(ca_directory)
    with tempfile.TemporaryDirectory(prefix='elderbrain-network-tls-') as directory:
        root = Path(directory)
        def run(args):
            result = subprocess.run(['openssl', *args], stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=20)
            if result.returncode:
                raise ValueError('Unable to prepare network confirmation TLS')
        run(['req', '-new', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(root / 'key.pem'),
             '-out', str(root / 'request.pem'), '-subj', '/CN=Elderbrain network confirmation',
             '-addext', 'subjectAltName=IP:' + address, '-addext', 'extendedKeyUsage=serverAuth'])
        (root / 'key.pem').chmod(0o600)
        run(['x509', '-req', '-in', str(root / 'request.pem'), '-CA', str(ca / 'ca.crt'),
             '-CAkey', str(ca / 'ca.key'), '-set_serial', '0x' + secrets.token_hex(16),
             '-out', str(root / 'certificate.pem'), '-days', '1', '-copy_extensions', 'copy'])
        result = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        result.minimum_version = ssl.TLSVersion.TLSv1_2
        result.load_cert_chain(root / 'certificate.pem', root / 'key.pem')
        return result
