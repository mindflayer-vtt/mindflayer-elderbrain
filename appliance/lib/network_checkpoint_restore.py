"""Private checkpoint/network handoff; no raw file or public API entry point.

The network worker owns timed activation. This coordinator owns quiescing,
checkpoint pins and maintenance exclusion until that worker reaches a terminal
state. Recovery must use the same persistent network journal, never infer that
a failed request means staging did not happen.
"""
import json
import re
from contextlib import nullcontext
from pathlib import Path
import time
import uuid

from backup_service import save_record
from checkpoint_staging import network_files
from local_snapshots import validate_pin


TERMINAL = (None, 'completed', 'failed', 'recovered', 'rolled-back')


def request(value):
    if (not isinstance(value, dict)
            or set(value) != {'checkpoint', 'interface', 'confirmationDigest', 'confirmRestore', 'confirmDowntime'}
            or value['confirmRestore'] is not True or value['confirmDowntime'] is not True):
        raise ValueError('Confirm network checkpoint replacement and service downtime')
    validate_pin(value['checkpoint'], '0' * 32, 'restore')
    from network_config import request as network_request
    network_request({'interface': value['interface'], 'mode': 'dhcp'})
    digest = value['confirmationDigest']
    if not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest):
        raise ValueError('Invalid network confirmation digest')
    return dict(value)


def coordinator(state='/var/lib/mindflayer-elderbrain', runtime='/opt/mindflayer-elderbrain',
                *, host_root=Path('/'), network=None, maintenance=None):
    """Build the verified host implementation; callers still own API admission."""
    from backup_service import HostServices, Maintenance
    from checkpoint_compatibility import capture, require_compatible
    from local_snapshots import Snapshots
    from network_service import restore_files
    from network_worker import transaction
    from restore_service import persistent_identity
    from snapshot_service import stable_settings
    state, runtime = Path(state), Path(runtime)
    identity = persistent_identity(state, host_root)
    if identity is None:
        raise ValueError('Network checkpoint restore requires verified persistent storage')

    def guard():
        if persistent_identity(state, host_root) != identity:
            raise ValueError('Persistent storage changed during network checkpoint restore')

    snapshots = Snapshots(state, quiesce=nullcontext, guard=guard, compatibility=lambda: capture(runtime))

    def compatible(identifier):
        guard()
        records = {record['id']: record for record in snapshots.list()}
        if identifier not in records:
            raise ValueError('Completed checkpoint not found')
        require_compatible(records[identifier].get('compatibility'), capture(runtime), ['network'])

    return NetworkCheckpointRestore(
        maintenance or Maintenance(state / 'maintenance', HostServices(runtime)), snapshots,
        network or transaction(), compatible=compatible,
        exclusive=lambda: stable_settings(state), stage=restore_files)


class NetworkCheckpointRestore:
    def __init__(self, maintenance, snapshots, network, *, compatible, exclusive, stage):
        # snapshots must use a verified storage guard and null quiesce: we stop
        # writers ourselves. compatible must check the installed runtime again.
        self.maintenance, self.snapshots, self.network = maintenance, snapshots, network
        self.compatible, self.exclusive, self.stage = compatible, exclusive, stage

    def save(self, record, state):
        record['state'] = state
        save_record(self.maintenance.journal, record)

    def owned_network(self, owner):
        with self.network.locked():
            record = self.network.read()
        return record if record and record.get('restoreOwner') == owner else None

    def release(self, record, state, network=None):
        # Hold maintenance exclusion until unpin succeeds. A cleanup failure
        # must not make a new maintenance operation eligible to replace owner.
        self.snapshots.unpin_owner(record['id'], 'restore')
        if network:
            # A crash after the maintenance record becomes terminal may allow
            # another operation to replace it before the worker acknowledges
            # cleanup. Keep a credential-free receipt for that exact handoff.
            save_record(self.receipt(record['id']), {
                'owner': record['id'], 'id': network['id'], 'phase': network['phase']})
        record['finishedAt'] = time.time()
        self.save(record, state)

    def receipt(self, owner):
        validate_pin('0' * 32, owner, 'restore')
        return self.maintenance.directory / f'network-restore-{owner}.json'

    def start(self, identifier, interface, *, confirmation_digest=None, transaction_id=None):
        validate_pin(identifier, '0' * 32, 'restore')
        if transaction_id is not None:
            validate_pin(transaction_id, '0' * 32, 'restore')
        from network_config import request
        request({'interface': interface, 'mode': 'dhcp'})
        if confirmation_digest is not None and (not isinstance(confirmation_digest, str)
                or not re.fullmatch(r'[a-f0-9]{64}', confirmation_digest)):
            raise ValueError('Invalid network confirmation digest')
        self.compatible(identifier)
        with self.maintenance.locked():
            if self.maintenance.previous().get('state') not in TERMINAL:
                raise RuntimeError('Recover interrupted maintenance before network restore')
            record = {'operation': 'network-restore', 'id': uuid.uuid4().hex,
                      'sourceCheckpoint': identifier, 'components': ['network'],
                      'startedAt': time.time(), 'services': self.maintenance.services.snapshot()}
            self.save(record, 'stopping')
            try:
                with self.exclusive():
                    self.maintenance.services.stop(record['services'])
                    self.save(record, 'working')
                    self.snapshots.pin(identifier, record['id'], 'restore')
                    self.compatible(identifier)
                    archived = network_files(self.snapshots.root / identifier)
                    recovery = self.snapshots.create('before-restore', owner=record['id'], purpose='restore')
                    record['rollbackCheckpoint'] = recovery['id']
                    self.save(record, 'starting')
                # Graphics reads settings locks, so resume only after release.
                self.maintenance.services.resume(record['services'])
                # Durable before stage: the worker may apply immediately and
                # the caller may die before stage returns. No token is journaled.
                self.save(record, 'awaiting-network')
                options = {'restore_owner': record['id']}
                if confirmation_digest is not None:
                    options['confirmation_digest'] = confirmation_digest
                if transaction_id is not None:
                    options['transaction_id'] = transaction_id
                return self.stage(archived, interface, **options)
            except Exception:
                # A stage error can follow a durable handoff. Never release its
                # pins or mark maintenance terminal while networking is pending.
                self.recover_locked(record)
                raise

    def recover_locked(self, record):
        if record.get('operation') != 'network-restore':
            raise ValueError('Not a network checkpoint restore')
        validate_pin(record['sourceCheckpoint'], record['id'], 'restore')
        if record.get('state') in TERMINAL:
            return record
        network = self.owned_network(record['id'])
        if network:
            if record['state'] != 'awaiting-network':
                raise RuntimeError('Network restore handoff journal mismatch')
            if network['phase'] not in ('confirmed', 'rolled-back'):
                raise RuntimeError('Network restore still requires confirmation or rollback')
            self.release(record, 'completed' if network['phase'] == 'confirmed' else 'rolled-back', network)
        else:
            # No staged network operation exists. Resume may be repeated after
            # a crash, but never start services from the early-boot callback.
            self.maintenance.services.resume(record['services'])
            self.release(record, 'rolled-back')
        return record

    def recover(self):
        with self.maintenance.locked():
            return self.recover_locked(self.maintenance.previous())

    def finalize(self, network):
        """Worker callback, safe before networking/Docker start: no service calls."""
        owner = network.get('restoreOwner')
        if not owner:
            return
        if network.get('phase') not in ('confirmed', 'rolled-back'):
            raise ValueError('Cannot finalize pending network restore')
        with self.maintenance.locked():
            record = self.maintenance.previous()
            if record.get('id') != owner or record.get('operation') != 'network-restore':
                expected = {'owner': owner, 'id': network['id'], 'phase': network['phase']}
                try:
                    receipt = json.loads(self.receipt(owner).read_text())
                except FileNotFoundError:
                    raise RuntimeError('Network restore owner mismatch') from None
                if receipt != expected:
                    raise RuntimeError('Network restore completion receipt mismatch')
                return
            # Re-read under the network lock rather than trusting a stale callback.
            current = self.owned_network(owner)
            if not current or current['id'] != network['id'] or current['phase'] != network['phase']:
                raise RuntimeError('Network restore transaction changed during cleanup')
            if record.get('state') not in ('completed', 'rolled-back', 'awaiting-network'):
                raise RuntimeError('Network restore services were not resumed before handoff')
            self.recover_locked(record)
