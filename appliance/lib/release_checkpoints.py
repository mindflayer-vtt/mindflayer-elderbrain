"""Pinned pre-update checkpoints and retryable data rollback under update locks."""
from contextlib import nullcontext
import hashlib
import os
from pathlib import Path
import uuid

from checkpoint_compatibility import capture, validate
from host_bindings import ALIASES, refresh
from local_snapshots import Snapshots, validate_pin
from restore_service import DATA_ROOTS, persistent_identity
from restore_transaction import RestoreTransaction, sync_directory


class UpdateCheckpoints:
    def __init__(self, state, runtime, maintenance, *, host_root=Path('/')):
        self.state, self.runtime, self.maintenance = Path(state), Path(runtime), maintenance
        self.host_root = Path(host_root)
        self.identity = persistent_identity(self.state, self.host_root)
        if self.identity is None:
            raise ValueError('Update checkpoints require verified persistent storage')
        self.snapshots = Snapshots(self.state, quiesce=nullcontext, guard=self.guard,
                                   compatibility=lambda: capture(self.runtime))

    def guard(self):
        if persistent_identity(self.state, self.host_root) != self.identity:
            raise ValueError('Persistent storage changed during update checkpoint handling')

    def targets(self):
        # Never replace the mounted data root, snapshots, jobs or maintenance
        # journals. Those are the control plane that makes rollback recoverable.
        names = (*DATA_ROOTS, 'keypad-installations', 'host/runtime',
                 *(('host/' + name) for name in ALIASES))
        return {name: self.state / name for name in names}

    def checkpoint(self, record):
        self.guard()
        record['rollbackCheckpoint'] = self.snapshots.create(
            'before-update', owner=record['id'], purpose='update')['id']

    def release(self, record):
        if record.get('state') not in ('completed', 'rolled-back'):
            raise ValueError('Cannot release an unfinished update checkpoint')
        self.guard()
        # Works even when capture completed just before the checkpoint ID could
        # be written to the outer journal. Retention, not this hook, deletes data.
        self.snapshots.unpin_owner(record['id'], 'update')

    def restore(self, record):
        """Caller holds update locks and has stopped writers and restored old code."""
        self.guard()
        identifier, owner = record.get('rollbackCheckpoint'), record.get('id')
        validate_pin(identifier, owner, 'update')
        self.snapshots.pin(identifier, owner, 'update')
        known = {item['id']: item for item in self.snapshots.list()}
        if identifier not in known or known[identifier]['reason'] != 'before-update':
            raise ValueError('Completed pre-update checkpoint is missing')
        metadata = validate(known[identifier].get('compatibility'))
        if (metadata['applianceVersion'] != (self.runtime / 'VERSION').read_text().strip()
                or metadata['composeSha256'] != hashlib.sha256((self.runtime / 'compose.yaml').read_bytes()).hexdigest()):
            raise ValueError('Restore the previous runtime before rolling back its data')
        targets = self.targets()
        sources = {name: self.snapshots.root / identifier / name for name in targets}
        for source in sources.values():
            if source.resolve() != source or not source.is_dir():
                raise ValueError('Checkpoint is missing a canonical user-data scope')
        journal = self.maintenance.directory / ('update-data-' + owner + '.json')
        transaction = RestoreTransaction(journal, targets)
        if journal.exists():
            status = transaction.read()['state']
            if status == 'committed':
                self.refresh()
                return
            # A partial checkpoint restore is itself reversible. Return to its
            # starting state, retain its evidence, then retry from the same RO
            # checkpoint. No in-place copying into partially replaced directories.
            transaction.rollback()
            self.refresh()
            os.rename(journal, journal.with_name(journal.stem + '-attempt-' + uuid.uuid4().hex + '.json'))
            sync_directory(journal.parent)
        self.guard()
        transaction.prepare(sources)
        transaction.apply()
        self.refresh()
        transaction.commit()

    def refresh(self):
        self.guard()
        refresh(self.state, self.identity['data_uuid'], ALIASES, host_root=self.host_root)
