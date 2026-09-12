"""Detached root-only QEMU supervisor for the real authenticated browser form.

Usage: controller.py ROOT_PRIVATE_TEST_DIRECTORY
Directory contains password (private fixture) and browser.mjs (public test code).
Restores even a confirmed transaction, independently of SSH/browser lifetime.
"""
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time
import ssl
import urllib.request

sys.path.insert(0, '/opt/mindflayer-elderbrain')
from network_staging import fingerprint, snapshot
from network_worker import transaction


def main():
    assert os.geteuid() == 0
    assert subprocess.check_output(['systemd-detect-virt'], text=True).strip() in ('qemu', 'kvm')
    root = Path(sys.argv[1])
    assert root.parent == Path('/tmp') and root.name.startswith('elderbrain-network-auth-')
    assert root.stat().st_mode & 0o777 == 0o700 and root.stat().st_uid == 0
    original = fingerprint(snapshot())
    store = transaction()
    with store.locked():
        baseline = store.read()
        assert not baseline or baseline['phase'] in ('confirmed', 'rolled-back')
    # Compose returning does not imply the application is ready to serve login.
    context = ssl.create_default_context(cafile='/var/lib/mindflayer-elderbrain/traefik/tls/ca.crt')
    deadline = time.monotonic() + 30
    while True:
        try:
            with urllib.request.urlopen('https://127.0.0.1/elderbrain/health', context=context, timeout=2) as response:
                if response.status == 200:
                    break
        except OSError:
            pass
        assert time.monotonic() < deadline, 'Setup did not become ready'
        time.sleep(0.5)
    process = subprocess.Popen(['runuser', '-u', 'elderbrain-kiosk', '--', 'node', '/tmp/elderbrain-network-auth-browser.mjs'],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               text=True, start_new_session=True)
    record = None
    passed = False
    try:
        process.stdin.write(json.dumps({'password': (root / 'password').read_text().strip()}) + '\n')
        process.stdin.flush()
        deadline = time.monotonic() + 100
        while time.monotonic() < deadline:
            if select.select([process.stdout], [], [], 0.2)[0]:
                line = process.stdout.readline().strip()
                if line == 'capture-required':
                    with store.locked():
                        record = store.read()
                        assert record and record['id'] != (baseline or {}).get('id')
                        assert 'files' in record and record['interface'] == 'ens3'
                    process.stdin.write('captured\n')
                    process.stdin.flush()
                    print('Captured original transaction before allowing browser confirmation.', flush=True)
                elif line == 'passed':
                    passed = True
                elif line.startswith('failed:') and line[7:] in ('launch', 'old-address-login', 'form-apply',
                        'new-address-tls', 'old-page-confirmation', 'new-address-session',
                        'login-heading', 'login-password-field', 'login-submit', 'login-navigation'):
                    print(line, flush=True)
            if process.poll() is not None:
                break
        assert passed and process.wait(timeout=5) == 0, 'Authenticated browser workflow failed'
        with store.locked():
            assert store.read()['id'] == record['id'] and store.read()['phase'] == 'confirmed'
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        with store.locked():
            current = store.read()
            if record:
                assert current['id'] == record['id']
                record['phase'] = 'pending'
                store.restore(record)
            elif current and current['id'] != (baseline or {}).get('id') and current['phase'] not in ('confirmed', 'rolled-back'):
                store.restore(current)
        assert fingerprint(snapshot()) == original
        addresses = json.loads(subprocess.check_output(['ip', '-j', '-4', 'address', 'show', 'dev', 'ens3']))
        assert {item['local'] for link in addresses for item in link.get('addr_info', [])} == {'10.0.2.15'}
        (root / 'result.json').write_text(json.dumps({'passed': passed, 'restored': True}))
        print('Restored original DHCP configuration and exact Netplan hierarchy.', flush=True)
    print('PASS: authenticated UI apply, old-page confirmation, isolated new-address login and CSRF.', flush=True)


if __name__ == '__main__':
    main()
