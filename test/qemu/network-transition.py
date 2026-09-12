"""Disposable QEMU-only real DHCP -> static -> timed DHCP rollback test.

Run as a detached systemd service: SSH is expected to disconnect while the
guest's address differs from the user-network port forwarding destination.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, '/opt/mindflayer-elderbrain')
from network_staging import fingerprint, prepare, snapshot
from network_worker import transaction


def addresses():
    links = json.loads(subprocess.check_output(['ip', '-j', '-4', 'address', 'show', 'dev', 'ens3']))
    return {item['local'] for link in links for item in link.get('addr_info', [])}


def main():
    assert os.geteuid() == 0
    assert subprocess.check_output(['systemd-detect-virt'], text=True).strip() in ('qemu', 'kvm')
    assert addresses() == {'10.0.2.15'}, 'Requires the disposable QEMU user-network fixture'
    subprocess.run(['systemctl', 'is-active', '--quiet', 'elderbrain-network-watchdog'], check=True)
    original = fingerprint(snapshot())
    store = transaction()
    candidate = prepare({'interface': 'ens3', 'mode': 'static', 'address': '10.0.2.20',
                         'prefix': 24, 'gateway': '10.0.2.2', 'dns': ['10.0.2.3']},
                        mac=Path('/sys/class/net/ens3/address').read_text().strip())
    assert candidate['fingerprint'] == original
    staged = store.stage(candidate['changes'], 'ens3', seconds=45, fingerprint=original)
    print('Staged real static IPv4 candidate with a 45-second rollback deadline.', flush=True)
    observed_static = restarted = restored = False
    last_observation = None
    try:
        deadline = time.monotonic() + 130
        while time.monotonic() < deadline:
            record = store.read()
            assert record['id'] == staged['id']
            current_addresses = addresses()
            observation = (record['phase'], sorted(current_addresses))
            if observation != last_observation:
                print('Observed phase and IPv4 addresses:', observation, flush=True)
                last_observation = observation
            if record['phase'] == 'pending' and current_addresses == {'10.0.2.20'}:
                subprocess.run(['runuser', '-u', 'systemd-network', '--', 'test', '-r',
                                '/run/systemd/network/10-netplan-ens3.network'], check=True)
                observed_static = True
                if not restarted:
                    subprocess.run(['systemctl', 'restart', 'elderbrain-network-watchdog'], check=True)
                    restarted = True
                    print('Observed new static address; restarted watchdog while confirmation was pending.', flush=True)
            if record['phase'] == 'rolled-back' and addresses() == {'10.0.2.15'}:
                assert fingerprint(snapshot()) == original, 'Original hierarchy was not restored exactly'
                assert 'files' not in record
                restored = True
                break
            time.sleep(1)
        assert restored, 'Timed rollback did not restore DHCP within the test deadline'
        assert observed_static and restarted, 'Candidate never reached a usable pending state'
        subprocess.run(['systemctl', 'is-active', '--quiet', 'elderbrain-network-watchdog'], check=True)
        print('PASS: real static address applied; watchdog restart preserved timeout; DHCP and exact sources restored.', flush=True)
    finally:
        record = store.read()
        if record and record['id'] == staged['id'] and record['phase'] not in ('confirmed', 'rolled-back'):
            store.cancel(staged['id'])


if __name__ == '__main__':
    main()
