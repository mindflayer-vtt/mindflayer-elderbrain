"""Journal the fixed Compose/startup-unit switch for legacy offline migration.

No containers are recreated: only future startup policy changes. The caller must
install matching independent boot recovery before invoking this internal API.
"""
import hashlib
import json
from pathlib import Path
import re
import uuid

from backup_service import save_record
from release_baseline import render, output, SERVICES
from release_interlocks import update_admission
from release_runtime import private_directory, read_regular
from restore_service import persistent_identity
from restore_transaction import RestoreTransaction
from snapshot_service import stable_settings


class Migration:
    def __init__(self, maintenance, *, host_root=Path('/')):
        self.maintenance = maintenance
        self.services = maintenance.services
        self.root = Path(host_root).absolute()
        self.state = self.root / 'var/lib/mindflayer-elderbrain'
        self.runtime = self.root / 'opt/mindflayer-elderbrain'
        self.identity = persistent_identity(self.state, self.root)
        if self.identity is None:
            raise ValueError('Baseline migration requires verified persistent storage')

    def guard(self):
        if persistent_identity(self.state, self.root) != self.identity:
            raise ValueError('Persistent storage changed during baseline migration')

    def transaction(self, record):
        identity = record.get('id')
        if not isinstance(identity, str) or not re.fullmatch('[a-f0-9]{32}', identity):
            raise ValueError('Invalid baseline migration identity')
        return RestoreTransaction(self.maintenance.directory / ('baseline-' + identity + '.json'), {
            'compose': self.runtime / 'compose.yaml',
            'stack': self.root / 'etc/systemd/system/elderbrain-stack.service'})

    def sources(self, prepared, stack_unit, *, run):
        prepared = private_directory(prepared)
        receipt = json.loads(read_regular(prepared / 'baseline.json', 65536))
        if (receipt.get('format') != 1 or receipt.get('state') != 'baseline-prepared'
                or receipt.get('activationReady') is not False
                or not isinstance(receipt.get('images'), dict) or set(receipt['images']) != SERVICES):
            raise ValueError('Invalid prepared baseline')
        original = read_regular(prepared / 'previous-compose.yaml', 1024 ** 2)
        generated = read_regular(prepared / 'compose.yaml', 1024 ** 2)
        if (hashlib.sha256(original).hexdigest() != receipt.get('sourceSha256')
                or hashlib.sha256(generated).hexdigest() != receipt.get('composeSha256')
                or read_regular(self.runtime / 'compose.yaml', 1024 ** 2) != original
                or render(original, receipt['images']) != generated):
            raise ValueError('Prepared baseline or live configuration changed')
        # Immutable IDs must still be cached. Never repair a missing cache by
        # contacting a registry or silently substituting a mutable tag.
        resolved = output(['docker', 'compose', '--project-directory', str(self.runtime),
            '--env-file', str(self.runtime / 'appliance.env'), '--profile', 'foundry',
            '-f', str(self.runtime / 'compose.yaml'), 'config', '--format', 'json'], run=run, cwd=self.runtime)
        services = resolved.get('services') if isinstance(resolved, dict) else None
        if not isinstance(services, dict) or set(services) != SERVICES:
            raise ValueError('Current baseline service set changed')
        for name, image in receipt['images'].items():
            reference = services[name].get('image') if isinstance(services[name], dict) else None
            if not isinstance(reference, str) or not reference or reference.startswith('-'):
                raise ValueError('Current baseline image reference changed')
            inspected = output(['docker', 'image', 'inspect', reference], run=run, cwd=self.runtime)
            if (not isinstance(inspected, list) or len(inspected) != 1
                    or not isinstance(inspected[0], dict) or inspected[0].get('Id') != image
                    or inspected[0].get('Os') != 'linux' or inspected[0].get('Architecture') != 'amd64'):
                raise ValueError('Prepared baseline image is unavailable or changed')
        # stack_unit is caller-authenticated installer code, never a path from
        # baseline metadata. Transaction validates fixed destination paths.
        read_regular(Path(stack_unit), 65536)
        return {'compose': prepared / 'compose.yaml', 'stack': Path(stack_unit)}

    def install(self, prepared, stack_unit, *, require_bootstrap, run):
        with update_admission(self.state), self.maintenance.locked(), stable_settings(self.state):
            if self.maintenance.previous().get('state') not in (None, 'completed', 'failed', 'recovered', 'rolled-back'):
                raise RuntimeError('Recover unfinished maintenance before baseline migration')
            self.guard()
            require_bootstrap()  # Must prove this recovery implementation is retained.
            sources = self.sources(prepared, stack_unit, run=run)
            saved = self.services.snapshot()  # Rejects a running/restarting stack unit.
            record = {'operation': 'baseline', 'id': uuid.uuid4().hex,
                      'state': 'installing', 'activationReady': False}
            transaction = self.transaction(record)
            save_record(self.maintenance.journal, record)
            try:
                transaction.prepare(sources)
                transaction.apply()
                self.services.run(['systemctl', 'daemon-reload'])
                self.services.validate()
                self.services.health_check(saved)
                self.guard()
                transaction.commit()
                record['state'] = 'completed'
                save_record(self.maintenance.journal, record)
                return record
            except Exception:
                self.recover_locked(record)
                raise

    def recover_locked(self, record):
        self.guard()
        if record.get('operation') != 'baseline':
            raise ValueError('Not a baseline migration')
        if record.get('state') in ('completed', 'rolled-back'):
            return record
        transaction = self.transaction(record)
        committed = transaction.journal.exists() and transaction.read()['state'] == 'committed'
        if transaction.journal.exists() and not committed:
            transaction.rollback()
        self.services.run(['systemctl', 'daemon-reload'])
        record['state'] = 'completed' if committed else 'rolled-back'
        save_record(self.maintenance.journal, record)
        return record

    def recover(self, *, early):
        with update_admission(self.state), self.maintenance.locked(), stable_settings(self.state):
            record = self.maintenance.previous()
            if record.get('state') not in ('completed', 'rolled-back'):
                if not early:
                    raise RuntimeError('Recover baseline files before starting writers')
                self.services.assert_quiescent()
            return self.recover_locked(record)
