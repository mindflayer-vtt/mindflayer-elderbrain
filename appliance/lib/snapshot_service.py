"""Host checkpoint coordinator; API/job entry points are added separately."""
from contextlib import contextmanager, ExitStack
import fcntl
import json
import os
import argparse
from pathlib import Path

from backup_service import Maintenance, HostServices
from local_snapshots import Snapshots
from storage_guard import check


@contextmanager
def stable_settings(state):
    """Hold existing transaction locks; never checkpoint an unconfirmed change."""
    with ExitStack() as stack:
        for name in ('display-preview', 'network-transaction'):
            directory = Path(state) / name
            directory.mkdir(mode=0o700, exist_ok=True)
            descriptor = os.open(directory / 'lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            stack.callback(os.close, descriptor)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError('Settings operation in progress') from error
            file = directory / 'state.json'
            if file.exists():
                record = json.loads(file.read_text())
                if record and record.get('phase') not in ('confirmed', 'rolled-back'):
                    raise RuntimeError('Confirm or revert pending settings before checkpointing')
        yield


def store(state='/var/lib/mindflayer-elderbrain', runtime='/opt/mindflayer-elderbrain'):
    state = Path(state)
    guard = lambda: check(target=str(state))
    guard()
    maintenance = Maintenance(state / 'maintenance', HostServices(Path(runtime)))
    @contextmanager
    def quiesce():
        # The existing maintenance lock also excludes backup, restore and flashing.
        # Settings locks release before graphics resumes (its preparation reads them).
        with maintenance.window('snapshot', exclusive=lambda: stable_settings(state)):
            yield
    from checkpoint_compatibility import capture
    return Snapshots(state, guard=guard, quiesce=quiesce, compatibility=lambda: capture(runtime))


def retention_settings(value=None, state='/var/lib/mindflayer-elderbrain', runtime='/opt/mindflayer-elderbrain'):
    snapshots = store(state, runtime)
    if value is None:
        return snapshots.retention()
    maintenance = Maintenance(Path(state) / 'maintenance', HostServices(Path(runtime)))
    with maintenance.locked():
        if maintenance.previous().get('state') not in (None, 'completed', 'failed', 'recovered', 'rolled-back'):
            raise RuntimeError('Recover interrupted maintenance before changing retention')
        return snapshots.retention(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('create', 'list', 'recover', 'restore'))
    parser.add_argument('--checkpoint')
    parser.add_argument('--component', action='append', default=[])
    parser.add_argument('--confirm-restore', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Requires root')
    snapshots = store()
    if args.operation == 'create':
        result = {'state': 'completed', 'checkpoint': snapshots.create('manual')}
    elif args.operation == 'list':
        result = {'state': 'ready', 'checkpoints': snapshots.list()}
    elif args.operation == 'restore':
        if not args.checkpoint or not args.component or not args.confirm_restore:
            parser.error('restore requires --checkpoint ID --component NAME --confirm-restore')
        from checkpoint_restore import restore
        runtime = Path('/opt/mindflayer-elderbrain')
        maintenance = Maintenance(snapshots.state / 'maintenance', HostServices(runtime))
        result = restore(args.checkpoint, args.component, snapshots.state, runtime, maintenance)
    else:
        runtime = Path('/opt/mindflayer-elderbrain')
        maintenance = Maintenance(snapshots.state / 'maintenance', HostServices(runtime))
        if maintenance.previous().get('operation') == 'restore':
            from restore_service import recover_host
            recover_host(snapshots.state, runtime, maintenance)
        elif maintenance.previous().get('operation') == 'network-restore':
            from network_checkpoint_restore import coordinator
            coordinator(snapshots.state, runtime, maintenance=maintenance).recover()
        else:
            maintenance.recover()
        snapshots.recover()
        result = {'state': 'recovered'}
    print(json.dumps(result))


if __name__ == '__main__':
    main()
