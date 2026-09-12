"""Real Btrfs update-data rollback fixture; no live runtime or data changes."""
from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'appliance/lib'))
from backup_service import Maintenance
from host_bindings import ALIASES, refresh
from release_checkpoints import UpdateCheckpoints
from restore_transaction import RestoreTransaction
from snapshot_service import stable_settings


def command(*args):
    return subprocess.check_output(args, text=True).strip()


assert os.geteuid() == 0
assert Path('/sys/class/dmi/id/product_name').read_text().startswith('Standard PC')
assert command('lsblk', '-dn', '-o', 'SERIAL', '/dev/vda') == 'elderbrain-vm-test'
assert Path('/proc/self/ns/mnt').readlink() != Path('/proc/1/ns/mnt').readlink(), 'Private mount namespace required'
root = Path(tempfile.mkdtemp(prefix='elderbrain-update-checkpoints-', dir='/tmp'))
print('Evidence: ' + str(root), flush=True)
disk = root / 'fixture.btrfs'
with disk.open('xb') as stream:
    stream.truncate(1024 ** 3)
command('mkfs.btrfs', str(disk))
device = command('losetup', '--find', '--show', str(disk))
state = root / 'mounted'
state.mkdir()
host = root / 'host'
host.mkdir()
mounted = False
try:
    command('mount', '-t', 'btrfs', device, str(state))
    mounted = True
    identity = {'data_uuid': command('findmnt', '-no', 'UUID', '--mountpoint', str(state))}
    def guard(*args):
        assert command('findmnt', '-no', 'UUID', '--mountpoint', str(state)) == identity['data_uuid']
        return identity
    runtime = root / 'runtime'
    runtime.mkdir()
    (runtime / 'VERSION').write_text('fixture\n')
    (runtime / 'compose.yaml').write_text('fixture-compose')
    compatibility = {'schema': 1, 'applianceVersion': 'fixture',
                     'composeSha256': hashlib.sha256(b'fixture-compose').hexdigest(), 'images': {}}
    maintenance = Maintenance(state / 'maintenance', None)
    with ExitStack() as patches:
        patches.enter_context(patch('release_checkpoints.persistent_identity', side_effect=guard))
        patches.enter_context(patch('release_checkpoints.capture', return_value=compatibility))
        adapter = UpdateCheckpoints(state, runtime, maintenance, host_root=host)
        for name, target in adapter.targets().items():
            target.mkdir(parents=True)
            (target / 'fixture').write_text('original:' + name)
        for relative in ALIASES.values():
            (host / relative).mkdir(parents=True)
        refresh(state, identity['data_uuid'], ALIASES, host_root=host)
        owner = uuid.uuid4().hex
        record = {'id': owner, 'state': 'checkpointing'}
        with maintenance.locked(), stable_settings(state):
            adapter.checkpoint(record)
            checkpoint = adapter.snapshots.root / record['rollbackCheckpoint']
            assert command('btrfs', 'property', 'get', '-t', 's', str(checkpoint), 'ro') == 'ro=true'
            assert list(adapter.snapshots.root.glob('*.' + owner + '.pin'))
            for target in adapter.targets().values():
                (target / 'fixture').write_text('changed by new runtime')
            apply = RestoreTransaction.apply
            def crash(transaction):
                apply(transaction)
                raise SystemExit('simulated process loss before bind refresh/commit')
            try:
                with patch.object(RestoreTransaction, 'apply', crash):
                    adapter.restore(record)
            except SystemExit:
                pass
            else:
                raise AssertionError('Crash injection did not run')
            adapter.restore(record)
            adapter.restore(record)  # Completed replay must be harmless.
            for name, target in adapter.targets().items():
                assert (target / 'fixture').read_text() == 'original:' + name
                assert (checkpoint / name / 'fixture').read_text() == 'original:' + name
            for name, relative in ALIASES.items():
                assert (state / 'host' / name).samefile(host / relative)
            assert len(list(maintenance.directory.glob('*-attempt-*.json'))) == 1
            record['state'] = 'rolled-back'
            adapter.release(record)
            assert not list(adapter.snapshots.root.glob('*.' + owner + '.pin'))
            assert checkpoint.is_dir()
    print('PASS: real RO checkpoint, crash/retry data rollback, host bind refresh, replay and pin cleanup', flush=True)
finally:
    for relative in reversed(list(ALIASES.values())):
        alias = host / relative
        if subprocess.run(['mountpoint', '-q', str(alias)]).returncode == 0:
            command('umount', str(alias))
    if mounted:
        command('umount', str(state))
    command('losetup', '--detach', device)
