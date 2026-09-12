"""Root-only disposable Btrfs restore fixture; run in a private mount namespace.

Real Btrfs, pins, staging, transactions and rollback archives; simulated service
health/runtime metadata. Does not qualify actual Foundry/container behavior.
"""
from contextlib import nullcontext, ExitStack
import json
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

import backup_archive
from backup_service import Maintenance
import checkpoint_restore
from checkpoint_staging import DEFAULT_CONFIG
from local_snapshots import Snapshots
import restore_service
from restore_transaction import RestoreTransaction


def command(*args):
    return subprocess.check_output(args, text=True).strip()


assert Path('/sys/class/dmi/id/product_name').read_text().startswith('Standard PC')
assert command('lsblk', '-dn', '-o', 'SERIAL', '/dev/vda') == 'elderbrain-vm-test'
assert Path('/proc/self/ns/mnt').readlink() != Path('/proc/1/ns/mnt').readlink(), 'Private namespace required'
root = Path(tempfile.mkdtemp(prefix='elderbrain-checkpoint-restore-', dir='/tmp'))
disk = root / 'fixture.btrfs'
with disk.open('xb') as stream:
    stream.truncate(1024 ** 3)
command('mkfs.btrfs', str(disk))
device = command('losetup', '--find', '--show', str(disk))
state = root / 'mounted'
state.mkdir()
mounted = False
try:
    command('mount', '-t', 'btrfs', device, str(state))
    mounted = True
    identity = {'data_uuid': command('findmnt', '-no', 'UUID', '--mountpoint', str(state))}
    def guard(*args):
        assert command('findmnt', '-no', 'UUID', '--mountpoint', str(state)) == identity['data_uuid']
        return identity
    compatibility = {'schema': 1, 'applianceVersion': 'fixture', 'composeSha256': 'a' * 64,
                     'images': {'foundry': 'sha256:' + 'b' * 64}}
    for directory in ('elderbrain/secrets', 'foundry', 'backups'):
        (state / directory).mkdir(parents=True)
    config = state / 'elderbrain/config.json'
    world = state / 'foundry/world-fixture'
    config.write_text(json.dumps({**DEFAULT_CONFIG, 'domain': 'old.local'}))
    world.write_text('archived-world')
    store = Snapshots(state, quiesce=nullcontext, guard=guard, compatibility=lambda: compatibility)
    source = store.create('manual')
    config.write_text(json.dumps({**DEFAULT_CONFIG, 'domain': 'current.local', 'configured': True}))
    world.write_text('current-world')
    class Services:
        reject = False
        stopped = False
        def snapshot(self):
            return {'compose': [], 'graphics': False}
        def stop(self, saved):
            self.stopped = True
        def validate(self):
            guard()
        def resume_restored(self, saved):
            if self.reject and world.read_text() == 'archived-world':
                raise RuntimeError('simulated unhealthy Foundry')
            self.stopped = False
    services = Services()
    maintenance = Maintenance(state / 'maintenance', services)
    def rollback(destination, state, runtime, maintenance, **kwargs):
        assert services.stopped
        archive = destination / ('fixture-' + kwargs['operation']['id'] + '.tar.zst')
        backup_archive.create(archive, {'elderbrain': state / 'elderbrain', 'foundry': state / 'foundry'},
                              version='fixture', identity='fixture')
        backup_archive.validate(archive)
        return {'archive': str(archive)}
    with ExitStack() as patches:
        for name in ('checkpoint_restore.persistent_identity', 'restore_service.persistent_identity'):
            patches.enter_context(patch(name, side_effect=guard))
        for name in ('checkpoint_restore.capture', 'checkpoint_compatibility.capture'):
            patches.enter_context(patch(name, return_value=compatibility))
        patches.enter_context(patch('host_bindings.refresh'))  # No actual OS aliases in this fixture.
        patches.enter_context(patch('checkpoint_restore.create_backup', side_effect=rollback))
        def restore(components):
            return checkpoint_restore.restore(source['id'], components, state, root, maintenance, host_root=root)
        result = restore(['preferences'])
        assert result['state'] == 'completed'
        assert json.loads(config.read_text())['domain'] == 'old.local'
        assert json.loads(config.read_text())['configured'] is True
        assert world.read_text() == 'current-world'
        assert not store.pins()
        recovery = store.root / result['rollbackCheckpoint']
        assert json.loads((recovery / 'elderbrain/config.json').read_text())['domain'] == 'current.local'
        assert command('btrfs', 'property', 'get', '-t', 's', str(recovery), 'ro') == 'ro=true'
        services.reject = True
        try:
            restore(['foundry'])
        except RuntimeError as error:
            assert 'unhealthy' in str(error)
        else:
            raise AssertionError('Unhealthy activation did not roll back')
        assert world.read_text() == 'current-world'
        assert maintenance.previous()['state'] == 'rolled-back' and not store.pins()
        services.reject = False
        apply = RestoreTransaction.apply
        def crash(transaction):
            apply(transaction)
            raise SystemExit('simulated process loss')
        with patch.object(RestoreTransaction, 'apply', crash):
            try:
                restore(['foundry'])
            except SystemExit:
                pass
            else:
                raise AssertionError('Crash injection did not run')
        assert world.read_text() == 'archived-world' and store.pins()
        result = restore_service.recover_host(state, root, maintenance, host_root=root)
        assert result['state'] == 'rolled-back'
        assert world.read_text() == 'current-world' and not store.pins()
        assert json.loads(config.read_text())['domain'] == 'old.local'
    print('PASS: real Btrfs selective activation, before-restore checkpoints, health rollback, crash recovery and pin release; ' + str(root))
finally:
    if mounted:
        command('umount', str(state))
    command('losetup', '--detach', device)
