"""Detached, disposable-QEMU-only test of a killed real network apply."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, '/opt/mindflayer-elderbrain')
from network_staging import fingerprint, prepare, snapshot
from network_worker import transaction

SERVICE = 'elderbrain-network-watchdog.service'
OVERRIDE = Path('/run/systemd/system') / (SERVICE + '.d') / '90-interruption-test.conf'


def addresses():
    data = json.loads(subprocess.check_output(['ip', '-j', '-4', 'address', 'show', 'dev', 'ens3']))
    return {item['local'] for link in data for item in link.get('addr_info', [])}


def systemctl(*args):
    return subprocess.check_output(['systemctl', *args], text=True, timeout=20).strip()


assert os.geteuid() == 0
assert subprocess.check_output(['systemd-detect-virt'], text=True).strip() in ('qemu', 'kvm')
assert addresses() == {'10.0.2.15'}
assert not OVERRIDE.exists(), 'Never replace an existing test override'
assert systemctl('is-active', SERVICE) == 'active'
original = fingerprint(snapshot())
store = transaction()
staged = None
with tempfile.TemporaryDirectory(prefix='elderbrain-apply-interruption-') as directory:
    wrapper = Path(directory) / 'netplan'
    shutil.copyfile('/tmp/elderbrain-netplan-interrupt-wrapper.py', wrapper)
    wrapper.chmod(0o755)
    OVERRIDE.parent.mkdir(parents=True, exist_ok=True)
    OVERRIDE.write_text('[Service]\nEnvironment="PATH=' + directory + ':/usr/sbin:/usr/bin:/sbin:/bin"\n')
    try:
        systemctl('daemon-reload')
        systemctl('restart', SERVICE)
        candidate = prepare({'interface': 'ens3', 'mode': 'static', 'address': '10.0.2.20',
                             'prefix': 24, 'gateway': '10.0.2.2', 'dns': ['10.0.2.3']},
                            mac=Path('/sys/class/net/ens3/address').read_text().strip())
        assert candidate['fingerprint'] == original
        staged = store.stage(candidate['changes'], 'ens3', seconds=90, fingerprint=original)
        killed = False
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            record = store.read()
            assert record['id'] == staged['id']
            if not killed and (Path(directory) / 'paused').exists() and record['phase'] == 'applying':
                assert addresses() == {'10.0.2.20'}, 'Real static apply did not complete before the injected pause'
                systemctl('kill', '--signal=SIGKILL', SERVICE)
                killed = True
                print('Killed watchdog cgroup after actual static apply, with durable phase still applying.', flush=True)
            if killed and record['phase'] == 'rolled-back' and addresses() == {'10.0.2.15'}:
                assert fingerprint(snapshot()) == original
                assert 'files' not in record
                assert systemctl('is-active', SERVICE) == 'active'
                print('PASS: restarted production watchdog restored DHCP and exact Netplan sources after interrupted apply.', flush=True)
                break
            time.sleep(0.2)
        else:
            raise AssertionError('Interrupted apply did not recover within deadline')
    finally:
        OVERRIDE.unlink(missing_ok=True)
        systemctl('daemon-reload')
        systemctl('restart', SERVICE)
        if staged:
            record = store.read()
            if record['id'] == staged['id'] and record['phase'] not in ('confirmed', 'rolled-back'):
                store.cancel(staged['id'])
