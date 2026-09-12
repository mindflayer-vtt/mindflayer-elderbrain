"""Read-only whole-data checkpoints; orchestration must quiesce all writers.

Selective restore uses a checkpoint's logical
components, never a wholesale replacement of the mounted Btrfs top-level.
"""
import fcntl
import json
import math
import os
import re
from pathlib import Path
import secrets
import shutil
import stat
import subprocess
import time
import tempfile

from storage_guard import check


def validate_pin(identifier, owner, purpose):
    if any(not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{32}', value)
           for value in (identifier, owner)):
        raise ValueError('Invalid checkpoint or pin owner ID')
    if purpose not in ('update', 'restore', 'pending-backup'):
        raise ValueError('Invalid checkpoint pin purpose')


def validate_retention(value):
    if (not isinstance(value, dict) or set(value) != {'enabled', 'keep'}
            or type(value['enabled']) is not bool or type(value['keep']) is not int
            or not 1 <= value['keep'] <= 1000):
        raise ValueError('Retention requires enabled true/false and keep between 1 and 1000')
    return value


def validate_nested(output):
    # Btrfs snapshots are not recursive. Refuse any user-data subvolume until
    # coordinated multi-subvolume capture is implemented; never omit it silently.
    for line in output.splitlines():
        prefix, separator, path = line.partition(' path ')
        if not separator or not prefix.startswith('ID ') or not re.fullmatch(r'snapshots/[a-f0-9]{32}', path):
            raise ValueError('Unsupported nested data subvolume; checkpoint would be incomplete')


def retention_candidates(records, keep, protected=()):
    if type(keep) is not int or not 1 <= keep <= 1000:
        raise ValueError('Keep between 1 and 1000 checkpoints')
    if any(not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{32}', value) for value in protected):
        raise ValueError('Invalid protected checkpoint ID')
    ordered = sorted(records, key=lambda value: (value['createdAt'], value['id']), reverse=True)
    retained = {value['id'] for value in ordered[:keep]} | set(protected)
    return [value['id'] for value in reversed(ordered) if value['id'] not in retained]


class Snapshots:
    def __init__(self, state, *, quiesce, guard=None, run=subprocess.run, compatibility=None):
        self.state = Path(state)
        self.root = self.state / 'snapshots'
        self.quiesce, self.guard, self.run = quiesce, guard or (lambda: check(target=str(self.state))), run
        self.compatibility = compatibility

    def command(self, *args):
        return self.run(list(args), check=True, capture_output=True, text=True, timeout=120).stdout.strip()

    def prepare(self):
        self.guard()
        self.root.mkdir(mode=0o700, exist_ok=True)
        info = self.root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise ValueError('Snapshot storage must be a private root-owned directory')
        if self.root.stat().st_dev != self.state.stat().st_dev:
            raise ValueError('Snapshot storage must be on the data filesystem')

    def records(self):
        """Caller holds the store lock. Corruption blocks all retention deletions."""
        result = []
        for file in self.root.glob('*.json'):
            identifier = file.stem
            if not re.fullmatch(r'[a-f0-9]{32}', identifier):
                raise ValueError('Unexpected checkpoint metadata')
            descriptor = os.open(file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor) as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077 or info.st_size > 4096:
                    raise ValueError('Unsafe checkpoint metadata')
                value = json.load(stream)
            if (not isinstance(value, dict) or value.get('version') != 1 or value.get('id') != identifier
                    or type(value.get('createdAt')) not in (int, float) or not math.isfinite(value['createdAt'])
                    or value.get('reason') not in ('manual', 'before-update', 'before-restore', 'before-shutdown')):
                raise ValueError('Invalid checkpoint metadata')
            destination = self.root / identifier
            info = destination.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_ino != 256:
                raise ValueError('Checkpoint is not a real Btrfs subvolume')
            if self.command('btrfs', 'property', 'get', '-t', 's', str(destination), 'ro') != 'ro=true':
                raise ValueError('Checkpoint is no longer read-only')
            public = {key: value[key] for key in ('version', 'id', 'createdAt', 'reason')}
            if 'compatibility' in value:
                from checkpoint_compatibility import validate
                public['compatibility'] = validate(value['compatibility'])
            result.append(public)
        return sorted(result, key=lambda value: (value['createdAt'], value['id']), reverse=True)

    def list(self):
        self.prepare()
        with open(self.root / '.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            return self.records()

    def sync_directory(self):
        descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def read_retention(self):
        try:
            descriptor = os.open(self.root / '.retention', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return {'enabled': False, 'keep': 10}
        with os.fdopen(descriptor) as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077 or info.st_size > 4096:
                raise ValueError('Unsafe retention settings')
            return validate_retention(json.load(stream))

    def retention(self, value=None):
        if value is not None:
            validate_retention(value)
        self.prepare()
        with open(self.root / '.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX if value is not None else fcntl.LOCK_SH)
            current = self.read_retention()
            if value is None:
                return current
            descriptor, temporary = tempfile.mkstemp(prefix='.retention-', dir=self.root)
            try:
                with os.fdopen(descriptor, 'w') as stream:
                    json.dump(value, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.root / '.retention')
                self.sync_directory()
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return value

    def pins(self):
        """Caller holds the store lock. Invalid pins block deletion, never expire."""
        result = []
        for file in self.root.glob('*.pin'):
            descriptor = os.open(file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor) as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077 or info.st_size > 4096:
                    raise ValueError('Unsafe checkpoint pin')
                value = json.load(stream)
            if not isinstance(value, dict) or value.get('version') != 1:
                raise ValueError('Invalid checkpoint pin')
            validate_pin(value.get('id'), value.get('owner'), value.get('purpose'))
            if file.name != value['id'] + '.' + value['owner'] + '.pin':
                raise ValueError('Checkpoint pin filename mismatch')
            result.append(value)
        return result

    def pinned_records(self, purpose):
        """Return fully validated purpose pins and checkpoints under one lock."""
        validate_pin('0' * 32, '0' * 32, purpose)
        self.prepare()
        with open(self.root / '.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            records = {value['id']: value for value in self.records()}
            result = []
            for pin in self.pins():
                if pin['purpose'] != purpose:
                    continue
                checkpoint = records.get(pin['id'])
                if checkpoint is None:
                    raise ValueError('Checkpoint pin has no complete checkpoint')
                result.append({'pin': pin, 'checkpoint': checkpoint})
            return result

    def write_pin(self, identifier, owner, purpose):
        """Caller holds exclusive lock; durable before publishing a checkpoint."""
        validate_pin(identifier, owner, purpose)
        value = {'version': 1, 'id': identifier, 'owner': owner, 'purpose': purpose}
        path = self.root / (identifier + '.' + owner + '.pin')
        for existing in self.pins():
            if existing['id'] == identifier and existing['owner'] == owner:
                if existing != value:
                    raise ValueError('Checkpoint pin owner already has another purpose')
                return
        with open(path, 'x') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        self.sync_directory()

    def pin(self, identifier, owner, purpose):
        validate_pin(identifier, owner, purpose)
        self.prepare()
        with open(self.root / '.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if identifier not in {record['id'] for record in self.records()}:
                raise ValueError('Completed checkpoint not found')
            self.write_pin(identifier, owner, purpose)

    def unpin(self, identifier, owner, purpose):
        """Only an explicit matching operation releases its own reservation."""
        validate_pin(identifier, owner, purpose)
        self.prepare()
        with open(self.root / '.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            for value in self.pins():
                if value['id'] == identifier and value['owner'] == owner:
                    if value['purpose'] != purpose:
                        raise ValueError('Checkpoint pin purpose mismatch')
                    (self.root / (identifier + '.' + owner + '.pin')).unlink()
                    self.sync_directory()
                    return

    def unpin_owner(self, owner, purpose):
        """Release a terminal operation's pins, including unjournaled captures.

        The caller must hold its operation lock and have durably completed or
        rolled back. Checkpoints themselves remain untouched, including orphans.
        """
        validate_pin('0' * 32, owner, purpose)
        self.prepare()
        with open(self.root / '.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            pins = self.pins()  # Validate everything before changing protection.
            for value in pins:
                if value['owner'] == owner and value['purpose'] == purpose:
                    (self.root / (value['id'] + '.' + owner + '.pin')).unlink()
            self.sync_directory()

    def finish_deletions(self):
        """Caller holds exclusive lock; only durable, validated intents are resumed."""
        protected = {value['id'] for value in self.pins()}
        for pending in self.root.glob('*.deleting'):
            identifier = pending.stem
            if identifier in protected:
                raise ValueError('Pending deletion conflicts with a checkpoint pin')
            if not re.fullmatch(r'[a-f0-9]{32}', identifier):
                raise ValueError('Invalid pending checkpoint deletion')
            descriptor = os.open(pending, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor) as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077 or info.st_size > 4096:
                    raise ValueError('Unsafe pending deletion metadata')
                metadata = json.load(stream)
            if not isinstance(metadata, dict) or metadata.get('id') != identifier or metadata.get('version') != 1:
                raise ValueError('Invalid pending deletion metadata')
            self.guard()
            destination = self.root / identifier
            try:
                info = destination.lstat()
            except FileNotFoundError:
                pass  # Prior committed deletion finished before its intent was cleared.
            else:
                if not stat.S_ISDIR(info.st_mode) or info.st_ino != 256:
                    raise ValueError('Pending deletion is not a real Btrfs subvolume')
                if self.command('btrfs', 'property', 'get', '-t', 's', str(destination), 'ro') != 'ro=true':
                    raise ValueError('Pending deletion is not read-only')
                self.command('btrfs', 'subvolume', 'delete', '--commit-after', str(destination))
            pending.unlink()
            self.sync_directory()

    def recover(self):
        self.prepare()
        with open(self.root / '.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.finish_deletions()

    def prune(self, keep, *, protected=()):
        """Explicit retention only; caller supplies active restore/upload pins."""
        self.prepare()
        with open(self.root / '.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return self.prune_locked(keep, protected=protected)

    def prune_locked(self, keep, *, protected=()):
        self.finish_deletions()
        records = self.records()  # verify every candidate before any deletion
        candidates = retention_candidates(records, keep,
                                          [*protected, *(value['id'] for value in self.pins())])
        for identifier in candidates:
            self.guard()
            os.rename(self.root / (identifier + '.json'), self.root / (identifier + '.deleting'))
            self.sync_directory()  # Durable intent before irreversible subvolume deletion.
            self.finish_deletions()
        self.sync_directory()
        return candidates

    def create(self, reason, *, owner=None, purpose=None):
        if reason not in ('manual', 'before-update', 'before-restore', 'before-shutdown'):
            raise ValueError('Invalid checkpoint reason')
        if owner is not None or purpose is not None:
            validate_pin('0' * 32, owner, purpose)
        self.prepare()
        with open(self.root / '.lock', 'a') as lock:
            os.fchmod(lock.fileno(), 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.guard()
            retention = self.read_retention()
            if shutil.disk_usage(self.state).free < 512 * 1024 ** 2:
                raise ValueError('Insufficient free space for a checkpoint')
            identifier = secrets.token_hex(16)
            destination = self.root / identifier
            # Nothing is declared complete until all writers have stopped,
            # the snapshot is durable, and its read-only property is verified.
            with self.quiesce():
                self.guard()
                compatibility = None
                if self.compatibility is not None:
                    from checkpoint_compatibility import validate
                    compatibility = validate(self.compatibility())
                validate_nested(self.command('btrfs', 'subvolume', 'list', '-o', str(self.state)))
                self.command('sync', '-f', str(self.state))
                self.command('btrfs', 'subvolume', 'snapshot', '-r', str(self.state), str(destination))
                if self.command('btrfs', 'property', 'get', '-t', 's', str(destination), 'ro') != 'ro=true':
                    raise ValueError('Checkpoint is not read-only')
                self.command('btrfs', 'filesystem', 'sync', str(self.state))
                metadata = {'version': 1, 'id': identifier, 'createdAt': time.time(), 'reason': reason}
                if compatibility is not None:
                    metadata['compatibility'] = compatibility
                if owner is not None:
                    self.write_pin(identifier, owner, purpose)
                # Exclusive creation: incomplete orphan snapshots remain for
                # diagnosis, never silently deleted or listed as complete.
                with open(self.root / (identifier + '.json'), 'x') as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    json.dump(metadata, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            if retention['enabled']:
                self.prune_locked(retention['keep'], protected=[identifier])
            return metadata
