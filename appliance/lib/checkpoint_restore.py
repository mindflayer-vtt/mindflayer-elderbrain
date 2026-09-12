"""Journaled activation of logical checkpoint components, with health rollback."""
from contextlib import nullcontext
from pathlib import Path
import tempfile

from backup_service import create_backup
from checkpoint_compatibility import capture, require_compatible
from checkpoint_components import selection
from checkpoint_staging import stage
from local_snapshots import Snapshots, validate_pin
from restore_service import (RestoreCoordinator, checkpoint_hooks, checkpoint_targets,
                             persistent_identity, alias_refresher)


def restore(identifier, components, state, runtime, maintenance, *, host_root=Path('/')):
    selected = selection(components)
    if set(selected) - {'preferences', 'keypad-settings', 'foundry'}:
        raise ValueError('Selected component requires a dedicated restore coordinator')
    validate_pin(identifier, '0' * 32, 'restore')
    state, runtime = Path(state), Path(runtime)
    identity = persistent_identity(state, host_root)
    if identity is None:
        raise ValueError('Checkpoint restore requires verified persistent storage')
    def guard():
        if persistent_identity(state, host_root) != identity:
            raise ValueError('Persistent storage changed during checkpoint restore')
    snapshots = Snapshots(state, quiesce=nullcontext, guard=guard)
    def compatible():
        guard()
        records = {record['id']: record for record in snapshots.list()}
        if identifier not in records:
            raise ValueError('Completed checkpoint not found')
        require_compatible(records[identifier].get('compatibility'), capture(runtime), selected)
    compatible()  # Reject incompatible selections before interrupting services.
    keys = set()
    if 'preferences' in selected:
        keys.update(('preferences', 'checkpoint-retention'))
    if 'keypad-settings' in selected:
        keys.update(('keypad-settings', 'keypad-records', 'keypad-expectations'))
    if 'foundry' in selected:
        keys.add('foundry')
    known = checkpoint_targets(state)
    targets = {key: known[key] for key in keys}
    hooks = checkpoint_hooks(state, runtime, host_root, identity)

    # The coordinator acquires maintenance/settings locks and stops writers
    # before reading current values for the merge. No stale pre-stop projection.
    with tempfile.TemporaryDirectory(prefix='checkpoint-restore-', dir=maintenance.directory) as temporary:
        def sources(record):
            snapshots.pin(identifier, record['id'], 'restore')
            compatible()  # Recheck after pinning and stopping writers.
            record['sourceCheckpoint'] = identifier
            record['components'] = list(selected)
            staged, mapping = stage(state, snapshots.root / identifier, Path(temporary) / 'staged', list(selected))
            if mapping != targets:
                raise ValueError('Checkpoint staging target mismatch')
            return staged
        def rollback(record):
            return create_backup(state / 'backups', state, runtime, maintenance,
                                 host_root=host_root, operation=record)['archive']
        return RestoreCoordinator(maintenance, targets, rollback,
                                  refresh_targets=alias_refresher(state, host_root, keys, identity),
                                  **hooks).restore(sources)
