"""VM-only real static change and host HTTPS confirmation; restores originals."""
import base64
import http.client
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import time

sys.path.insert(0, '/opt/mindflayer-elderbrain')
from network_service import start, status
from network_staging import fingerprint, snapshot
from network_worker import transaction, run_netplan


def post(identifier, token, address='10.0.2.20'):
    context = ssl.create_default_context(cafile='/var/lib/mindflayer-elderbrain/traefik/tls/ca.crt')
    client = http.client.HTTPSConnection(address, 10444, context=context, timeout=5)
    # The listener is bound to ens3. Route the local VM test client through that
    # same device; external-client reachability remains a separate test gate.
    def connect(address, timeout, source_address=None):
        connection = socket.socket()
        connection.settimeout(timeout)
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, b'ens3\0')
        try:
            connection.connect(address)
            return connection
        except Exception:
            connection.close()
            raise
    client._create_connection = connect
    try:
        client.request('POST', '/confirm', json.dumps({'id': identifier, 'token': token}),
                       {'Content-Type': 'application/json'})
        response = client.getresponse()
        response.read()
        return response.status
    finally:
        client.close()


def main():
    assert os.geteuid() == 0
    assert subprocess.check_output(['systemd-detect-virt'], text=True).strip() in ('qemu', 'kvm')
    original = snapshot()
    store = transaction()
    change = start({'interface': 'ens3', 'mode': 'static', 'address': '10.0.2.20',
                    'prefix': 24, 'gateway': '10.0.2.2', 'dns': ['10.0.2.3']})
    print('Staged static address through production host service; waiting for TLS readiness.', flush=True)
    owned = [fingerprint(original)]
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            current = status()
            if current.get('confirmation') == 'https://10.0.2.20:10444/confirm':
                break
            time.sleep(1)
        else:
            raise AssertionError('Confirmation listener never became ready')
        owned.append(fingerprint(snapshot()))
        assert post(change['id'], 'x' * 43) == 409
        assert store.read()['phase'] == 'pending'
        assert post(change['id'], change['token']) == 200
        assert store.read()['phase'] == 'confirmed'
        assert 'confirmation' not in store.read()
        print('PASS: exact-IP CA-verified TLS endpoint rejected wrong token and confirmed real static configuration.', flush=True)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if not json.loads(Path('/run/elderbrain-network-confirmation/status.json').read_text())['ready']:
                break
            time.sleep(1)
        else:
            raise AssertionError('Listener did not close after confirmation')
        old_token = change['token']
        change = start({'interface': 'ens3', 'mode': 'dhcp', 'dns': []})
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if status().get('confirmation') == 'https://10.0.2.15:10444/confirm':
                break
            time.sleep(1)
        else:
            raise AssertionError('DHCP confirmation listener never became ready')
        owned.append(fingerprint(snapshot()))
        assert post(change['id'], old_token, '10.0.2.15') == 409
        assert post(change['id'], change['token'], '10.0.2.15') == 200
        assert store.read()['phase'] == 'confirmed'
        print('PASS: static-to-DHCP discovered the lease; old token rejected and new lease confirmed over TLS.', flush=True)
    finally:
        if store.read()['phase'] not in ('confirmed', 'rolled-back'):
            store.cancel(change['id'])
        # Restore only test-owned changes, refusing concurrent external edits.
        current = snapshot()
        assert fingerprint(current) in owned
        if fingerprint(current) != fingerprint(original):
            for name, source in original.items():
                if source['content'] != current[name]['content'] or source['mode'] != current[name]['mode']:
                    assert name.startswith('etc/netplan/')
                    store.replace(Path(name).name, base64.b64encode(source['content']).decode(), source)
            run_netplan('apply')
        assert fingerprint(snapshot()) == fingerprint(original)
        print('Restored exact original VM Netplan hierarchy and applied original networking.', flush=True)


if __name__ == '__main__':
    main()
