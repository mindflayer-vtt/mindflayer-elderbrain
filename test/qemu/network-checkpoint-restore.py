"""Installed-QEMU qualification: real checkpoint/job/TLS restore, stable IP.

Run as root in the disposable serial-identified appliance. Retains checkpoints
and private evidence; never prints configuration or the confirmation capability.
"""
import hashlib
import argparse
import http.client
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import sys
import tempfile
import time

assert os.geteuid() == 0
assert Path('/sys/class/dmi/id/product_name').read_text().startswith('Standard PC')
assert subprocess.check_output(['lsblk', '-dn', '-o', 'SERIAL', '/dev/vda'], text=True).strip() == 'elderbrain-vm-test'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--rollback', action='store_true', help='Withhold confirmation and verify real deadline rollback')
args = parser.parse_args()
sys.path.insert(0, '/opt/mindflayer-elderbrain')
from host_jobs import JobStore
from network_worker import transaction
from network_service import status
from snapshot_service import store

state = Path('/var/lib/mindflayer-elderbrain')
evidence = Path(tempfile.mkdtemp(prefix='network-restore-evidence-', dir='/root'))
snapshots = store()
jobs = JobStore(state / 'jobs')
network = transaction()
assert network.public(network.read())['phase'] in ('idle', 'confirmed', 'rolled-back')
sources = sorted(Path('/etc/netplan').glob('*.yaml'))
assert sources and all(source.is_file() and not source.is_symlink() for source in sources)
source = sources[0]
original = source.read_bytes()
(evidence / 'original.yaml').write_bytes(original)
os.chmod(evidence / 'original.yaml', 0o600)
print('Capturing source checkpoint', flush=True)
checkpoint = snapshots.create('manual')['id']
print('Source checkpoint captured', flush=True)
source.write_bytes(original + b'\n# disposable network restore qualification\n')
modified = source.read_bytes()
token = secrets.token_urlsafe(32)
digest = hashlib.sha256(token.encode()).hexdigest()
client = socket.socket(socket.AF_UNIX)
client.settimeout(15)
client.connect('/run/elderbrain/management.sock')
client.sendall(f'network-snapshot-restore-start {checkpoint} ens3 {digest}\n'.encode())
client.shutdown(socket.SHUT_WR)
reply = b''
while chunk := client.recv(65536):
    reply += chunk
client.close()
accepted = json.loads(reply)
assert accepted['ok'], 'Host bridge rejected restore'
job = json.loads(accepted['output'])
identifier = job['id']
(evidence / 'selection.json').write_text(json.dumps({'checkpoint': checkpoint, 'job': identifier}))
print('Restore admitted; restarting management to test worker independence', flush=True)
subprocess.run(['systemctl', 'restart', 'elderbrain-management.service'], check=True, timeout=30)
deadline = time.monotonic() + 600
last = None
while time.monotonic() < deadline:
    job = jobs.read(identifier)
    phase = job['state']
    if phase != last:
        print('Host job:', phase, flush=True)
        last = phase
    assert phase not in ('failed', 'interrupted'), 'Restore job failed; retain evidence for diagnosis'
    if phase == 'completed':
        break
    time.sleep(1)
else:
    raise RuntimeError('Observation deadline reached; inspect the existing job, do not restart it')
assert job['result']['id'] == identifier
assert token not in json.dumps(jobs.list())
deadline = time.monotonic() + 90
while time.monotonic() < deadline:
    current = status()
    if current.get('id') == identifier and current.get('confirmation'):
        break
    time.sleep(1)
else:
    raise RuntimeError('Confirmation listener unavailable; allow the existing rollback deadline')
from urllib.parse import urlsplit
endpoint = urlsplit(current['confirmation'])
assert endpoint.scheme == 'https' and endpoint.port == 10444 and endpoint.path == '/confirm'
if args.rollback:
    print('Withholding confirmation; waiting for the real host deadline', flush=True)
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        record = network.read()
        assert record['id'] == identifier
        if record['phase'] == 'rolled-back' and record.get('cleanupComplete'):
            break
        time.sleep(1)
    else:
        raise RuntimeError('Rollback observation expired; inspect this transaction without restarting it')
else:
    context = ssl.create_default_context(cafile=str(state / 'traefik/tls/ca.crt'))
    connection = http.client.HTTPSConnection(endpoint.hostname, endpoint.port, context=context, timeout=10)
    connection.request('POST', '/confirm', json.dumps({'id': identifier, 'token': token}), {'Content-Type': 'application/json'})
    response = connection.getresponse()
    assert response.status == 200, 'Direct TLS confirmation rejected'
    assert json.loads(response.read())['phase'] == 'confirmed'
    connection.close()
record = network.read()
assert record['id'] == identifier and record['phase'] == ('rolled-back' if args.rollback else 'confirmed') and record.get('cleanupComplete')
maintenance = json.loads((state / 'maintenance/maintenance.json').read_text())
assert maintenance['state'] == ('rolled-back' if args.rollback else 'completed')
assert not any(pin['owner'] == maintenance['id'] for pin in snapshots.pins())
assert source.read_bytes() == (modified if args.rollback else original)
rollback = snapshots.root / maintenance['rollbackCheckpoint'] / 'host/netplan' / source.name
assert rollback.read_bytes() == modified
subprocess.run(['systemctl', 'is-active', '--quiet', 'elderbrain-stack', 'elderbrain-management',
                'elderbrain-graphics', 'elderbrain-network-watchdog', 'elderbrain-network-confirmation'], check=True)
if args.rollback:
    # Remove only our exact comment after verified terminal rollback. No network
    # semantics changed, so this cleanup does not require a second netplan apply.
    assert source.read_bytes() == modified
    source.write_bytes(original)
    subprocess.run(['sync', '-f', str(source)], check=True)
(evidence / 'result.json').write_text(json.dumps({'state': 'passed', 'checkpoint': checkpoint,
    'job': identifier, 'rollbackCheckpoint': maintenance['rollbackCheckpoint'], 'mode': 'rollback' if args.rollback else 'confirm'}))
print('PASS: real checkpoint restore, management restart survival, ' +
      ('deadline rollback' if args.rollback else 'direct TLS confirmation') + ', cleanup and recovery contents', flush=True)
print('Private evidence:', evidence, flush=True)
