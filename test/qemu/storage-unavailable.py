"""Disposable QEMU only: prove missing data prevents writers, then restore mounts."""
from pathlib import Path
import subprocess


def run(*args, check=True):
    return subprocess.run(args, check=check, capture_output=True, text=True, timeout=120)


assert run('cat', '/sys/class/dmi/id/product_name').stdout.strip().startswith('Standard PC'), 'QEMU only'
assert run('lsblk', '-dn', '-o', 'SERIAL', '/dev/vda').stdout.strip() == 'elderbrain-vm-test', 'Disposable disk only'
assert Path('/etc/elderbrain/storage.json').is_file()
state = '/var/lib/mindflayer-elderbrain'
mount = run('systemd-escape', '--path', '--suffix=mount', state).stdout.strip()
units = ['docker.service', 'elderbrain-stack.service', 'elderbrain-management.service',
         'elderbrain-graphics.service', 'elderbrain-display-watchdog.service',
         'elderbrain-network-recovery.service', 'elderbrain-network-watchdog.service',
         'elderbrain-network-confirmation.service', 'elderbrain-admin-console.service']
active = [unit for unit in units if run('systemctl', 'is-active', '--quiet', unit, check=False).returncode == 0]
assert 'docker.service' in active and 'elderbrain-stack.service' in active
assert not Path('/run/systemd/system', mount).exists(), 'Unexpected runtime mount override'
try:
    run('systemctl', 'mask', '--runtime', mount)
    run('systemctl', 'stop', mount)
    assert run('findmnt', '--mountpoint', state, check=False).returncode != 0
    for unit in ('docker.service', 'elderbrain-stack.service', 'elderbrain-management.service'):
        assert run('systemctl', 'is-active', '--quiet', unit, check=False).returncode != 0, unit
    before = sorted(Path(state).iterdir())
    assert run('systemctl', 'start', 'elderbrain-stack.service', check=False).returncode != 0
    assert run('systemctl', 'is-active', '--quiet', 'docker.service', check=False).returncode != 0
    assert sorted(Path(state).iterdir()) == before, 'Created replacement data on OS partition'
    print('PASS: unavailable data mount stops writers and rejects stack startup without creating data')
finally:
    run('systemctl', 'unmask', '--runtime', mount)
    run('systemctl', 'reset-failed')
    run('systemctl', 'start', 'elderbrain-storage.service')
    run('systemctl', 'start', *active)
    print('Original storage mounts and previously active services restored')
