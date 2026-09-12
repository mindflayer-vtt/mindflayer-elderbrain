"""Detached QEMU controller: static browser confirmation, then exact DHCP cleanup.

The host supplies an existing root-private result directory. Independent of SSH,
this controller restores even a confirmed transaction after its test deadline.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, '/opt/mindflayer-elderbrain')
from network_service import start
from network_staging import fingerprint, snapshot
from network_worker import transaction


def addresses():
    links = json.loads(subprocess.check_output(['ip', '-j', '-4', 'address', 'show', 'dev', 'ens3']))
    return {item['local'] for link in links for item in link.get('addr_info', [])}


def main():
    assert os.geteuid() == 0
    assert subprocess.check_output(['systemd-detect-virt'], text=True).strip() in ('qemu', 'kvm')
    root = Path(sys.argv[1])
    assert root.parent == Path('/tmp') and root.name.startswith('elderbrain-network-browser-')
    assert root.stat().st_uid == 0 and root.stat().st_mode & 0o777 == 0o700
    assert addresses() == {'10.0.2.15'}
    original = fingerprint(snapshot())
    store = transaction()
    record = None
    confirmed = False
    try:
        result = start({'interface': 'ens3', 'mode': 'static', 'address': '10.0.2.20',
                        'prefix': 24, 'gateway': '10.0.2.2', 'dns': ['10.0.2.3']})
        with store.locked():
            record = store.read()
            assert record['id'] == result['id']
        # Only this private file carries the capability, never the journal.
        with (root / 'packet.json').open('x') as output:
            os.fchmod(output.fileno(), 0o600)
            json.dump({'id': result['id'], 'token': result['token']}, output)
        deadline = time.monotonic() + 85
        while time.monotonic() < deadline:
            with store.locked():
                current = store.read()
            assert current['id'] == result['id']
            if current['phase'] == 'confirmed':
                assert addresses() == {'10.0.2.20'}
                confirmed = True
                # Allow the browser to receive the TLS response before cleanup.
                time.sleep(5)
                break
            if current['phase'] == 'rolled-back':
                break
            time.sleep(1)
    finally:
        if record:
            with store.locked():
                assert store.read()['id'] == record['id']
                record['phase'] = 'pending'
                store.restore(record)
        assert addresses() == {'10.0.2.15'}
        assert fingerprint(snapshot()) == original
        (root / 'result.json').write_text(json.dumps({'confirmed': confirmed, 'restored': True}))
    assert confirmed, 'Browser did not confirm the static address'
    print('PASS: browser confirmed actual static IPv4; detached controller restored DHCP and exact sources.', flush=True)


if __name__ == '__main__':
    main()
