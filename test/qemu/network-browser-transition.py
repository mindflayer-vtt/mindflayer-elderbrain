"""Host-side real DHCP -> static browser confirmation -> DHCP QEMU gate.

Usage: python3 test/qemu/network-browser-transition.py MONITOR BACKEND
Requires current production network listener/admin_tls installed in the VM.
Uses real endpoints, with the scoped certificate pins documented by the browser
runner. Does not yet exercise submitting the authenticated Network form.
"""
import importlib.util
import json
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('external', HERE / 'network-external.py')
external = importlib.util.module_from_spec(spec)
spec.loader.exec_module(external)


def command(arguments, **kwargs):
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=15, **kwargs)
    if result.returncode:
        raise RuntimeError('VM command failed (private diagnostics suppressed)')
    return result.stdout.strip()


def main():
    kiosk_browser = '--kiosk-browser' in sys.argv[1:]
    monitor, backend = [arg for arg in sys.argv[1:] if arg != '--kiosk-browser']
    assert 'Hub -1 (' + backend + '):' in external.monitor(monitor, 'info usernet')
    original_ssh = list(external.SSH)
    forwards = []
    firewall = launched = False
    root = None
    try:
        external.ssh("import subprocess\nassert subprocess.check_output(['systemd-detect-virt'],text=True).strip() in ('qemu','kvm')")
        for host, guest in [(24443, 443), (24444, 10444), (2223, 22)]:
            reply = external.monitor(monitor, f'hostfwd_add {backend} tcp:127.0.0.1:{host}-10.0.2.20:{guest}')
            assert 'Could not' not in reply and 'Error' not in reply
            forwards.append(host)
        ca = external.ssh("from pathlib import Path\nprint(Path('/var/lib/mindflayer-elderbrain/traefik/tls/ca.crt').read_text())")
        context = ssl.create_default_context(cadata=ca)
        firewall = external.ssh("import subprocess\nprint('10444' not in subprocess.check_output(['ufw','status'],text=True))").strip() == 'True'
        if firewall:
            external.ssh("import subprocess\nsubprocess.run(['ufw','allow','10444/tcp'],check=True,stdout=subprocess.DEVNULL)")
        root = command([*original_ssh, 'mktemp -d /tmp/elderbrain-network-browser-XXXXXXXX'])
        assert root.startswith('/tmp/elderbrain-network-browser-') and root.replace('-', '').replace('/', '').isalnum()
        scp = ['scp', '-i', str(external.ROOT / '.qemu/id_ed25519'), '-o', 'IdentitiesOnly=yes',
               '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null', '-P', '2222']
        command([*scp, str(HERE / 'network-browser-transition-guest.py'), f'root@127.0.0.1:{root}/controller.py'])
        unit = Path(root).name
        command([*original_ssh, f'systemd-run --unit={unit} --property=UMask=0077 python3 {root}/controller.py {root}'])
        launched = True
        external.SSH = [*original_ssh]
        external.SSH[external.SSH.index('2222')] = '2223'
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            try:
                packet = json.loads(external.ssh(
                    "from pathlib import Path\nprint(Path(" + repr(root + '/packet.json') + ").read_text())"))
                certificates = []
                for port in (24443, 24444):
                    with socket.create_connection(('127.0.0.1', port), timeout=3) as connection:
                        with context.wrap_socket(connection, server_hostname='10.0.2.20') as secure:
                            certificates.append(ssl.DER_cert_to_PEM_cert(secure.getpeercert(binary_form=True)))
                break
            except (RuntimeError, OSError, ValueError):
                time.sleep(1)
        else:
            raise AssertionError('Static destination did not become available with valid TLS')
        packet.update(address='10.0.2.20', certificates=certificates)
        browser_command = ([*external.SSH, 'runuser -u elderbrain-kiosk -- node /tmp/elderbrain-network-browser-trust.mjs']
                           if kiosk_browser else ['node', str(HERE / 'network-browser.mjs')])
        result = subprocess.run(browser_command,
                                input=json.dumps(packet), text=True, capture_output=True, timeout=40)
        assert result.returncode == 0, 'Browser static confirmation failed (private diagnostics suppressed)'
        expected = ('PASS: kiosk Chromium trusts the installed CA, rejects wrong-IP TLS, and confirms without certificate exceptions.'
                    if kiosk_browser else 'PASS: real browser cross-origin confirmation and preflight.')
        assert result.stdout.strip() == expected
        print(expected, flush=True)
        print('Browser confirmed through the actual new static address with CA/IP-verified leaves.', flush=True)
    finally:
        external.SSH = original_ssh
        try:
            if launched:
                # The already-running detached controller owns restoration,
                # including after confirmation or host/browser failure.
                deadline = time.monotonic() + 130
                while time.monotonic() < deadline:
                    try:
                        result = json.loads(external.ssh(
                            "from pathlib import Path\nprint(Path(" + repr(root + '/result.json') + ").read_text())"))
                        assert result['restored'] is True
                        print('Detached controller restored DHCP and exact original Netplan sources.', flush=True)
                        break
                    except (RuntimeError, ValueError, OSError):
                        time.sleep(1)
                else:
                    raise AssertionError('Controller cleanup unverified; inspect its systemd unit before further testing')
        finally:
            try:
                if firewall:
                    external.ssh("import subprocess\nsubprocess.run(['ufw','--force','delete','allow','10444/tcp'],check=True,stdout=subprocess.DEVNULL)")
            finally:
                for port in reversed(forwards):
                    external.monitor(monitor, f'hostfwd_remove {backend} tcp:127.0.0.1:{port}')
    assert result['confirmed'] is True
    print('PASS: real static browser confirmation and independent DHCP restoration.', flush=True)


if __name__ == '__main__':
    main()
