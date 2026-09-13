"""VM-only test of live Traefik certificate reload; restores original files."""
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import time

sys.path.insert(0, '/opt/mindflayer-elderbrain')
from admin_tls import ensure_address, replace


def served(certificate, name):
    expected = ssl.PEM_cert_to_DER_cert(certificate.decode())
    context = ssl.create_default_context(cafile='/var/lib/mindflayer-elderbrain/traefik/tls/ca.crt')
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', 443), timeout=3) as connection:
                with context.wrap_socket(connection, server_hostname=name) as secure:
                    if secure.getpeercert(binary_form=True) == expected:
                        return
        except (OSError, ssl.SSLError):
            pass
        time.sleep(1)
    raise AssertionError('Proxy did not serve the expected CA-verified certificate')


def main():
    assert subprocess.check_output(['systemd-detect-virt'], text=True).strip() in ('qemu', 'kvm')
    root = Path('/var/lib/mindflayer-elderbrain/traefik')
    certificate, dynamic = root / 'tls/admin.crt', root / 'dynamic/admin-tls.yaml'
    original, configuration = certificate.read_bytes(), dynamic.read_bytes()
    try:
        ensure_address('10.0.2.20')
        served(certificate.read_bytes(), '10.0.2.20')
        assert dynamic.read_bytes() == configuration
        print('PASS: running Traefik serves refreshed certificate valid for new IP with existing CA.', flush=True)
    finally:
        replace(certificate, original)
        replace(dynamic, configuration)
        served(original, '127.0.0.1')
        print('Restored original certificate/configuration and verified live proxy reload.', flush=True)


if __name__ == '__main__':
    main()
