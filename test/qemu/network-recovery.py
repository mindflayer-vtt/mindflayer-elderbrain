"""VM-only interrupted-write reboot test; never changes address settings.

Run prepare, reboot the VM externally, then run check. This deliberately leaves
an unconfirmed on-disk candidate for the production boot service to recover.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, '/opt/mindflayer-elderbrain')
from network_staging import fingerprint, snapshot
from network_worker import transaction


def main():
    assert os.geteuid() == 0
    assert subprocess.check_output(['systemd-detect-virt'], text=True).strip() in ('qemu', 'kvm')
    marker = Path('/var/lib/mindflayer-elderbrain/network-recovery-test.json')
    store = transaction()
    if sys.argv[1:] == ['prepare']:
        assert not marker.exists(), 'Previous test still requires verification'
        subprocess.run(['systemctl', 'stop', 'elderbrain-network-watchdog'], check=True)
        files = snapshot()
        names = [name for name in files if name.startswith('etc/netplan/')]
        assert names, 'Expected an existing persistent Netplan source'
        name = names[0]
        before = files[name]['content']
        baseline = fingerprint(files)
        staged = store.stage({Path(name).name: {'before': before,
                             'after': before + b'\n# Elderbrain VM interrupted-write test\n'}},
                             'ens3', fingerprint=baseline)
        with store.locked():
            record = store.read()
            record['phase'] = 'applying'
            store.write(record)
            change = record['files'][Path(name).name]
            store.replace(Path(name).name, change['after'], {**change['before'], 'mode': 0o600})
        marker.write_text(json.dumps({'baseline': baseline, 'boot': store.boot, 'id': staged['id']}))
        marker.chmod(0o600)
        print('Prepared harmless interrupted write. Reboot this disposable VM, then run check.')
    elif sys.argv[1:] == ['check']:
        expected = json.loads(marker.read_text())
        assert store.boot != expected['boot'], 'VM has not rebooted'
        record = store.read()
        assert record['id'] == expected['id'] and record['phase'] == 'rolled-back'
        assert 'files' not in record
        assert fingerprint(snapshot()) == expected['baseline'], 'Original bytes/permissions/ownership not restored'
        for unit in ('elderbrain-network-recovery', 'elderbrain-network-watchdog', 'systemd-networkd'):
            subprocess.run(['systemctl', 'is-active', '--quiet', unit], check=True)
        def activated(unit):
            return int(subprocess.check_output(['systemctl', 'show', unit, '-p',
                       'ActiveEnterTimestampMonotonic', '--value'], text=True))
        assert 0 < activated('elderbrain-network-recovery') <= activated('systemd-networkd')
        status = subprocess.check_output(['networkctl', 'status', 'ens3', '--no-pager'], text=True)
        assert '/run/systemd/network/10-netplan-ens3.network' in status, 'Networkd did not use restored Netplan backend'
        subprocess.run(['runuser', '-u', 'systemd-network', '--', 'test', '-r',
                        '/run/systemd/network/10-netplan-ens3.network'], check=True)
        marker.unlink()
        print('PASS: reboot restored exact Netplan hierarchy before networkd activation; watchdog active.')
    else:
        raise SystemExit('Use prepare or check')


if __name__ == '__main__':
    main()
