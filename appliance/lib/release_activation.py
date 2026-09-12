"""Durable update switching; host adapters supply fixed targets and checkpoint IO.

Not a public update API. The source callback must reverify the complete prepared
runtime, images and dependencies, attach persistent aliases and check deployment
permissions. Recovery must run from a stable worker outside the replaced runtime.
"""
import time
import uuid

from appliance_release import verify
from backup_service import save_record
from restore_transaction import RestoreTransaction
from release_interlocks import update_admission
from snapshot_service import stable_settings


class Activation:
    def __init__(self, maintenance, targets, *, checkpoint, restore_checkpoint,
                 release_checkpoint, refresh, exclusive=None, admission=None, job_owner=None):
        self.maintenance = maintenance
        self.services = maintenance.services
        self.targets = targets
        self.checkpoint = checkpoint
        self.restore_checkpoint = restore_checkpoint
        self.release_checkpoint = release_checkpoint
        self.refresh = refresh
        self.job_owner = job_owner
        state = maintenance.directory.parent
        self.exclusive = exclusive or (lambda: stable_settings(state))
        self.admission = admission or (lambda: update_admission(state))

    def write(self, record, state):
        record['state'] = state
        save_record(self.maintenance.journal, record)

    def transaction(self, record):
        identity = record.get('id', '')
        if (not isinstance(identity, str) or len(identity) != 32
                or any(c not in '0123456789abcdef' for c in identity)):
            raise ValueError('Invalid update transaction identity')
        return RestoreTransaction(self.maintenance.directory / ('update-' + identity + '.json'), self.targets)

    def activate(self, manifest, signature, public_key, prepare_sources):
        release = verify(manifest, signature, public_key)
        if release['format'] != 2:
            raise ValueError('Activation requires a complete signed release')
        with self.admission(), self.maintenance.locked():
            if self.maintenance.previous().get('state') not in (None, 'completed', 'failed', 'recovered', 'rolled-back'):
                raise RuntimeError('Interrupted maintenance requires recovery first')
            # Trusted host adapter revalidates all inputs before interrupting any
            # service. Archive metadata never supplies the live target mapping.
            record = None
            try:
                with self.exclusive():
                    sources = prepare_sources(release)
                    if set(sources) != set(self.targets):
                        raise ValueError('Update sources do not match fixed host targets')
                    candidate = {'operation': 'update', 'id': uuid.uuid4().hex, 'version': release['version'],
                                 'startedAt': time.time(), 'services': self.services.snapshot(),
                                 'dataMayHaveChanged': False, 'dataRolledBack': False}
                    if self.job_owner is not None:
                        candidate['jobId'] = self.job_owner
                    transaction = self.transaction(candidate)
                    self.write(candidate, 'stopping')
                    record = candidate
                    self.services.stop(record['services'])
                    self.write(record, 'checkpointing')
                    self.checkpoint(record)  # Must be durable and pinned by operation ID.
                    if not record.get('rollbackCheckpoint'):
                        raise ValueError('Update requires a durable recovery checkpoint')
                    self.write(record, 'preparing-update')
                    transaction.prepare(sources)
                    self.write(record, 'installing-update')
                    transaction.apply()
                self.refresh()
                self.services.validate()
                # New processes can migrate/write data during health checks.
                # Record that fact BEFORE starting them, not after a failed check.
                record['dataMayHaveChanged'] = True
                self.write(record, 'verifying-update')
                self.services.resume_restored(record['services'])
                transaction.commit()
                self.write(record, 'completed')
                self.release_checkpoint(record)
                return record
            except Exception:
                if record is None:
                    raise  # Admission/preflight failure never stopped services.
                self.write(record, 'recovery-required')
                self.recover_locked(record)
                raise

    def recover(self):
        with self.admission(), self.maintenance.locked():
            return self.recover_locked(self.maintenance.previous())

    def recover_files(self):
        """Early boot only: caller orders this before every writer service.

No Docker/config/health commands or service starts occur here. Pins and the
nonterminal maintenance record survive until normal recovery verifies health.
"""
        with self.admission(), self.maintenance.locked():
            record = self.maintenance.previous()
            if record.get('operation') != 'update':
                raise ValueError('This is not an interrupted update')
            if record.get('state') in ('completed', 'rolled-back'):
                return record
            with self.exclusive():
                self.services.assert_quiescent()
                transaction = self.transaction(record)
                self.write(record, 'recovery-required')
                self.restore_files_locked(record, transaction)
                self.refresh()
            self.write(record, 'files-recovered')
            return record

    def restore_files_locked(self, record, transaction):
        """Private shared rollback step; caller proves writers stopped."""
        committed = transaction.journal.exists() and transaction.read()['state'] == 'committed'
        if transaction.journal.exists() and not committed:
            transaction.rollback()
        if not committed and record['dataMayHaveChanged'] and not record['dataRolledBack']:
            self.restore_checkpoint(record)
            record['dataRolledBack'] = True
            self.write(record, 'recovery-required')
        return committed

    def recover_locked(self, record):
        if record.get('operation') != 'update':
            raise ValueError('This is not an interrupted update')
        if record.get('state') in ('completed', 'rolled-back'):
            self.release_checkpoint(record)
            return record
        transaction = self.transaction(record)
        self.write(record, 'recovery-required')
        with self.exclusive():
            # Even a failed health check may leave new writers running. Never
            # replace code or restore data unless stopping them succeeds.
            self.services.stop(record['services'])
            committed = self.restore_files_locked(record, transaction)
        self.refresh()
        self.services.validate()
        self.services.resume_restored(record['services'])
        self.write(record, 'completed' if committed else 'rolled-back')
        self.release_checkpoint(record)
        return record
