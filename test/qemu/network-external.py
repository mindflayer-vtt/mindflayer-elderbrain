"""Host-side QEMU forwarding/UFW/TLS confirmation test; restores VM settings.

Uses the retained VM's default DHCP address. Run after the guest-local real
static/DHCP transition tests; this isolates the external ingress path.
Add --browser for real Chromium CORS/preflight through a CONNECT routing proxy.
Browser key exceptions are scoped to leaves independently CA/IP-verified here;
this does not test installation of the private CA in a user's trust store.
"""
import http.client
import json
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SSH = ['ssh', '-i', str(ROOT / '.qemu/id_ed25519'), '-o', 'IdentitiesOnly=yes',
       '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
       '-o', 'ConnectTimeout=5', '-p', '2222', 'root@127.0.0.1']


def ssh(code):
    result = subprocess.run([*SSH, 'python3 -'], input=code, text=True, capture_output=True, timeout=40)
    if result.returncode:
        raise RuntimeError('VM operation failed (private output suppressed)')
    return result.stdout


def monitor(path, command):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(3)
        connection.connect(path)
        def read():
            output = b''
            while not output.endswith(b'(qemu) '):
                part = connection.recv(8192)
                if not part:
                    raise RuntimeError('VM monitor disconnected')
                output += part
            return output.decode()
        read()
        connection.sendall(command.encode() + b'\n')
        return read()


def main():
    browser = '--browser' in sys.argv[1:]
    kiosk_browser = '--kiosk-browser' in sys.argv[1:]
    assert not (browser and kiosk_browser), 'Choose one browser mode'
    monitor_path, backend = [arg for arg in sys.argv[1:] if arg not in ('--browser', '--kiosk-browser')]
    assert 'Hub -1 (' + backend + '):' in monitor(monitor_path, 'info usernet')
    ssh("import subprocess\nassert subprocess.check_output(['systemd-detect-virt'], text=True).strip() in ('qemu','kvm')")
    forwarding = firewall = admin_forwarding = False
    packet = None
    try:
        reply = monitor(monitor_path, f'hostfwd_add {backend} tcp:127.0.0.1:24444-10.0.2.15:10444')
        assert 'Could not' not in reply and 'Error' not in reply
        forwarding = True
        if browser:
            reply = monitor(monitor_path, f'hostfwd_add {backend} tcp:127.0.0.1:24443-10.0.2.15:443')
            assert 'Could not' not in reply and 'Error' not in reply
            admin_forwarding = True
        firewall = ssh("import subprocess\nprint('10444' not in subprocess.check_output(['ufw','status'], text=True))").strip() == 'True'
        packet = json.loads(ssh("""
import json,sys
sys.path.insert(0,'/opt/mindflayer-elderbrain')
from network_service import start
from network_worker import transaction
result=start({'interface':'ens3','mode':'dhcp','dns':[]})
store=transaction()
with store.locked(): record=store.read()
print(json.dumps({'result':result,'record':record}))
"""))
        if firewall:
            ssh("import subprocess\nsubprocess.run(['ufw','allow','10444/tcp'],check=True,stdout=subprocess.DEVNULL)")
        ca = ssh("from pathlib import Path\nprint(Path('/var/lib/mindflayer-elderbrain/traefik/tls/ca.crt').read_text())")
        context = ssl.create_default_context(cadata=ca)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status = json.loads(ssh("import sys,json\nsys.path.insert(0,'/opt/mindflayer-elderbrain')\nfrom network_service import status\nprint(json.dumps(status()))"))
            if status.get('confirmation'):
                break
            time.sleep(1)
        else:
            raise AssertionError('No confirmation endpoint readiness')
        if kiosk_browser:
            result = subprocess.run(
                [*SSH, 'runuser -u elderbrain-kiosk -- node /tmp/elderbrain-network-browser-trust.mjs'],
                input=json.dumps({'id': packet['result']['id'], 'token': packet['result']['token']}),
                text=True, capture_output=True, timeout=45,
            )
            if result.returncode:
                raise AssertionError('Kiosk browser trust test failed (private diagnostics suppressed)')
            assert result.stdout.strip() == 'PASS: kiosk Chromium trusts the installed CA, rejects wrong-IP TLS, and confirms without certificate exceptions.'
            state = json.loads(ssh("import sys,json\nsys.path.insert(0,'/opt/mindflayer-elderbrain')\nfrom network_service import status\nprint(json.dumps(status()))"))
            assert state['id'] == packet['result']['id'] and state['phase'] == 'confirmed'
            print(result.stdout.strip(), flush=True)
            return
        if browser:
            # Verify both real leaves normally before granting the disposable
            # browser narrowly scoped public-key exceptions. No blanket TLS bypass.
            certificates = []
            for port in (24443, 24444):
                with socket.create_connection(('127.0.0.1', port), timeout=5) as connection:
                    with context.wrap_socket(connection, server_hostname='10.0.2.15') as secure:
                        certificates.append(ssl.DER_cert_to_PEM_cert(secure.getpeercert(binary_form=True)))
            result = subprocess.run(
                ['node', str(ROOT / 'qemu/network-browser.mjs')],
                input=json.dumps({'id': packet['result']['id'], 'token': packet['result']['token'],
                                  'certificates': certificates}),
                text=True, capture_output=True, timeout=45,
            )
            if result.returncode:
                raise AssertionError('Browser confirmation failed (private diagnostics suppressed)')
            assert result.stdout.strip() == 'PASS: real browser cross-origin confirmation and preflight.'
            status = json.loads(ssh("import sys,json\nsys.path.insert(0,'/opt/mindflayer-elderbrain')\nfrom network_service import status\nprint(json.dumps(status()))"))
            assert status['id'] == packet['result']['id'] and status['phase'] == 'confirmed'
            print(result.stdout.strip(), flush=True)
            return
        client = http.client.HTTPSConnection('10.0.2.15', 10444, context=context, timeout=5)
        client._create_connection = lambda address, timeout, source_address=None: socket.create_connection(('127.0.0.1',24444), timeout)
        try:
            client.request('POST','/confirm',json.dumps({'id':packet['result']['id'],'token':packet['result']['token']}),{'Content-Type':'application/json'})
            response=client.getresponse()
            assert response.status == 200 and json.loads(response.read())['phase'] == 'confirmed'
        finally:
            client.close()
        print('PASS: external host entered VM via ens3/UFW and confirmed using exact-IP, CA-verified TLS.', flush=True)
    finally:
        try:
            if packet:
                backup = json.dumps(packet['record'])
                ssh("import sys,json\nsys.path.insert(0,'/opt/mindflayer-elderbrain')\nfrom network_worker import transaction\nstore=transaction()\nrecord=json.loads(" + repr(backup) + ")\nwith store.locked():\n assert store.read()['id']==record['id']\n expected=dict(record['files'])\n record['phase']='pending'\n store.restore(record)\n assert all(store.file(name)==change['before'] for name,change in expected.items())\n")
        finally:
            try:
                if firewall:
                    ssh("import subprocess\nsubprocess.run(['ufw','--force','delete','allow','10444/tcp'],check=True,stdout=subprocess.DEVNULL)")
            finally:
                try:
                    if admin_forwarding:
                        monitor(monitor_path, f'hostfwd_remove {backend} tcp:127.0.0.1:24443')
                finally:
                    if forwarding:
                        monitor(monitor_path, f'hostfwd_remove {backend} tcp:127.0.0.1:24444')
        print('Removed test forwarding/firewall rule and restored original VM network configuration.', flush=True)


if __name__ == '__main__':
    main()
