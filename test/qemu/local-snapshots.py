"""Run as root in a private mount namespace in a disposable test VM."""
from contextlib import contextmanager
import errno
from pathlib import Path
import subprocess
import tempfile
from local_snapshots import Snapshots


def command(*args):
    return subprocess.check_output(args, text=True).strip()


root = Path(tempfile.mkdtemp(prefix='elderbrain-snapshot-', dir='/tmp'))
disk = root / 'fixture.btrfs'
with disk.open('xb') as stream:
    stream.truncate(1024 ** 3)
command('mkfs.btrfs', str(disk))
device = command('losetup', '--find', '--show', str(disk))
target = root / 'mounted'
target.mkdir()
mounted = False
try:
    command('mount', '-t', 'btrfs', device, str(target))
    mounted = True
    fixture = target / 'user-data'
    fixture.write_text('original')
    @contextmanager
    def quiesce():
        # This exclusive fixture has no application writers.
        yield
    def guard():
        assert command('findmnt', '-no', 'FSTYPE', '--mountpoint', str(target)) == 'btrfs'
    store = Snapshots(target, quiesce=quiesce, guard=guard)
    owner = 'a' * 32
    first = store.create('before-shutdown', owner=owner, purpose='pending-backup')
    snapshot = store.root / first['id']
    fixture.write_text('changed')
    assert (snapshot / 'user-data').read_text() == 'original'
    try:
        (snapshot / 'user-data').write_text('forbidden')
    except OSError as error:
        assert error.errno == errno.EROFS
    else:
        raise AssertionError('Snapshot accepted writes')
    second = store.create('before-update')
    assert (store.root / second['id'] / 'user-data').read_text() == 'changed'
    assert len(store.list()) == 2
    assert store.prune(1, protected=[first['id']]) == []
    # A new process/store must honor durable reservations without caller hints.
    store = Snapshots(target, quiesce=quiesce, guard=guard)
    assert store.prune(1) == []
    store.pin(first['id'], owner, 'pending-backup')  # idempotent
    store.pin(first['id'], 'b' * 32, 'restore')
    try:
        store.unpin(first['id'], owner, 'update')
    except ValueError:
        pass
    else:
        raise AssertionError('Wrong operation released a pin')
    store.unpin(first['id'], owner, 'pending-backup')
    assert store.prune(1) == []  # other owner still holds it
    store.unpin(first['id'], 'b' * 32, 'restore')
    malformed = store.root / ('c' * 32 + '.pin')
    malformed.write_text('{}')
    malformed.chmod(0o600)
    try:
        store.prune(1)
    except ValueError:
        pass
    else:
        raise AssertionError('Corrupt pin did not block retention')
    assert snapshot.exists()
    malformed.unlink()
    assert store.prune(1) == [first['id']]
    assert not snapshot.exists()
    assert [value['id'] for value in store.list()] == [second['id']]
    assert fixture.read_text() == 'changed'
    third = store.create('manual')
    original_run = store.run
    def interrupted(args, **kwargs):
        result = original_run(args, **kwargs)
        if args[:3] == ['btrfs', 'subvolume', 'delete']:
            raise RuntimeError('Simulated crash after committed deletion')
        return result
    store.run = interrupted
    try:
        store.prune(1)
    except RuntimeError:
        pass
    else:
        raise AssertionError('Interruption fixture did not run')
    assert list(store.root.glob('*.deleting'))
    store.run = original_run
    store.recover()
    assert not list(store.root.glob('*.deleting'))
    assert [value['id'] for value in store.list()] == [third['id']]
    assert fixture.read_text() == 'changed'
    assert store.retention() == {'enabled': False, 'keep': 10}
    store.retention({'enabled': True, 'keep': 1})
    assert (store.root / third['id']).exists()  # settings alone never delete
    store = Snapshots(target, quiesce=quiesce, guard=guard)
    assert store.retention() == {'enabled': True, 'keep': 1}
    fourth = store.create('manual')
    assert [value['id'] for value in store.list()] == [fourth['id']]
    store.pin(fourth['id'], owner, 'pending-backup')
    fifth = store.create('before-update')
    assert {value['id'] for value in store.list()} == {fourth['id'], fifth['id']}
    command('btrfs', 'subvolume', 'create', str(target / 'nested-user-data'))
    try:
        store.create('manual')
    except ValueError:
        pass
    else:
        raise AssertionError('Nested user data silently omitted')
    print('PASS: snapshots, durable multi-owner pins, protected retention, interrupted-delete recovery, source unchanged and nested-data rejection; ' + str(root))
finally:
    if mounted:
        command('umount', str(target))
    command('losetup', '--detach', device)
