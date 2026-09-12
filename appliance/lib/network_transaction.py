"""Persistent network transactions, driven independently of the HTTP request.

The caller must validate candidates with Netplan before staging. Confirmation
requires a trusted destination-address verifier; no permissive default is provided.
"""
import base64
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat
import time


class NetworkTransaction:
    def __init__(self, state, netplan, apply, verify_confirmation, clock=time.time, monotonic=time.monotonic, boot=None, verify_sources=None, on_terminal=None):
        self.state = Path(state)
        self.state.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.netplan = Path(netplan)
        self.apply = apply
        self.verify_confirmation = verify_confirmation
        self.verify_sources = verify_sources or (lambda _fingerprint: False)
        self.on_terminal = on_terminal
        self.clock, self.monotonic = clock, monotonic
        self.boot = boot or Path('/proc/sys/kernel/random/boot_id').read_text().strip()

    @contextmanager
    def locked(self):
        with open(self.state / 'lock', 'a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    def read(self):
        try:
            return json.loads((self.state / 'state.json').read_text())
        except FileNotFoundError:
            return None

    def write(self, record):
        temporary = self.state / ('.state-' + secrets.token_hex(16))
        with open(temporary, 'x') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(record, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.state / 'state.json')
        descriptor = os.open(self.state, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def filename(name):
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+\.yaml', name) or name.startswith('.'):
            raise ValueError('Invalid Netplan filename')
        return name

    def file(self, name):
        parent = os.open(self.netplan, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            try:
                descriptor = os.open(self.filename(name), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            except FileNotFoundError:
                # Absence is durable rollback state, distinct from an empty file.
                return {'bytes': None, 'mode': 0o600, 'uid': 0, 'gid': 0}
            with os.fdopen(descriptor, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 2 * 1024 * 1024:
                    raise ValueError('Invalid Netplan source file')
                return {'bytes': base64.b64encode(stream.read()).decode(), 'mode': stat.S_IMODE(info.st_mode),
                        'uid': info.st_uid, 'gid': info.st_gid}
        finally:
            os.close(parent)

    def replace(self, name, content, metadata):
        parent = os.open(self.netplan, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        temporary = '.network-' + secrets.token_hex(16)
        try:
            if content is None:
                try:
                    info = os.stat(self.filename(name), dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    return
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError('Refusing to remove an unsafe Netplan source')
                os.unlink(name, dir_fd=parent)
                os.fsync(parent)
                return
            descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(base64.b64decode(content, validate=True))
                stream.flush()
                if os.geteuid() == 0:
                    os.fchown(stream.fileno(), metadata['uid'], metadata['gid'])
                os.fchmod(stream.fileno(), metadata['mode'])
                os.fsync(stream.fileno())
            os.replace(temporary, self.filename(name), src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass
            os.close(parent)

    @staticmethod
    def public(record):
        return {key: record[key] for key in ('id', 'phase', 'deadline', 'interface')} if record else {'phase': 'idle'}

    def expired(self, record):
        return record['boot'] != self.boot or self.clock() >= record['deadline'] or self.monotonic() >= record['expires']

    def stage(self, changes, interface, seconds=120, fingerprint=None, confirmation=None, restore_owner=None, identifier=None):
        if identifier is not None and (not isinstance(identifier, str) or not re.fullmatch(r'[a-f0-9]{32}', identifier)):
            raise ValueError('Invalid network transaction identity')
        if restore_owner is not None and (not isinstance(restore_owner, str) or not re.fullmatch(r'[a-f0-9]{32}', restore_owner)):
            raise ValueError('Invalid network restore owner')
        if not isinstance(interface, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}', interface):
            raise ValueError('Invalid interface')
        if not 15 <= seconds <= 180 or not 1 <= len(changes) <= 64:
            raise ValueError('Invalid network transaction')
        if confirmation is not None:
            if (not isinstance(confirmation, dict) or set(confirmation) != {'digest', 'mode', 'address'}
                    or not isinstance(confirmation['digest'], str)
                    or not re.fullmatch(r'[a-f0-9]{64}', confirmation['digest'])
                    or confirmation['mode'] not in ('static', 'dhcp')):
                raise ValueError('Invalid confirmation binding')
            from network_config import unicast
            if confirmation['mode'] == 'static':
                unicast(confirmation['address'])
            elif confirmation['address'] is not None:
                raise ValueError('DHCP confirmation must discover the new address')
        with self.locked():
            if fingerprint is not None and (not isinstance(fingerprint, str) or not re.fullmatch(r'[a-f0-9]{64}', fingerprint) or not self.verify_sources(fingerprint)):
                raise ValueError('Netplan hierarchy changed before staging')
            current = self.read()
            if identifier is not None and current and current['id'] == identifier:
                raise ValueError('Network transaction identity already used')
            if current and current['phase'] not in ('confirmed', 'rolled-back'):
                raise ValueError('Network transaction already in progress')
            if current and current.get('restoreOwner') and not current.get('cleanupComplete'):
                raise ValueError('Previous network restore cleanup is pending')
            files = {}
            for name, change in changes.items():
                name = self.filename(name)
                original = self.file(name)
                original_bytes = base64.b64decode(original['bytes']) if original['bytes'] is not None else None
                if original_bytes != change['before']:
                    raise ValueError('Netplan source changed during preparation')
                if change['after'] is not None and (not isinstance(change['after'], bytes) or len(change['after']) > 2 * 1024 * 1024):
                    raise ValueError('Invalid Netplan candidate')
                if original_bytes is None and change['after'] is None:
                    raise ValueError('Network change has neither an existing nor a candidate file')
                files[name] = {'before': original, 'after':
                               base64.b64encode(change['after']).decode() if change['after'] is not None else None}
            record = {'id': identifier or secrets.token_hex(16), 'phase': 'staged', 'interface': interface,
                      'deadline': self.clock() + seconds, 'expires': self.monotonic() + seconds, 'boot': self.boot, 'files': files,
                      'fingerprint': fingerprint, 'confirmation': confirmation}
            if restore_owner is not None:
                record['restoreOwner'] = restore_owner
            self.write(record)  # Original bytes are durable before any network file changes.
            return self.public(record)

    def restore(self, record, activate=None):
        if record['phase'] == 'staged':
            record['phase'] = 'rolled-back'
            record.pop('files')
            record.pop('confirmation', None)
            self.write(record)
            return
        record['phase'] = 'rolling-back'
        self.write(record)
        for name, change in record['files'].items():
            current = self.file(name)
            if current['bytes'] not in (change['before']['bytes'], change['after']):
                raise ValueError('External edit conflicts with rollback; refusing to overwrite it')
        for name, change in record['files'].items():
            self.replace(name, change['before']['bytes'], change['before'])
        (activate or self.apply)()
        record['phase'] = 'rolled-back'
        record.pop('files')
        record.pop('confirmation', None)
        self.write(record)

    def finalize(self):
        # Checkpoint cleanup takes its own store lock. Never call it while the
        # network lock is held: checkpoint capture takes these locks in reverse.
        with self.locked():
            record = self.read()
        if (record and record['phase'] in ('confirmed', 'rolled-back')
                and not record.get('cleanupComplete') and self.on_terminal is not None):
            self.on_terminal(record)
            if record.get('restoreOwner'):
                with self.locked():
                    current = self.read()
                    if current and current['id'] == record['id'] and current['phase'] == record['phase']:
                        current['cleanupComplete'] = True
                        self.write(current)

    def recover_boot(self, generate):
        result = self._recover_boot(generate)
        self.finalize()
        return result

    def _recover_boot(self, generate):
        """Restore unconfirmed sources before network services start.

        Regenerate backend files without starting/restarting networking. A failed
        generation retains the recovery record for a later retry.
        """
        with self.locked():
            record = self.read()
            if record and record['phase'] not in ('confirmed', 'rolled-back'):
                self.restore(record, activate=generate)
            return self.public(record)

    def tick(self):
        result = self._tick()
        self.finalize()
        return result

    def _tick(self):
        with self.locked():
            record = self.read()
            if not record:
                return self.public(record)
            if record['phase'] in ('confirmed', 'rolled-back'):
                return self.public(record)
            if record['phase'] in ('applying', 'rolling-back') or self.expired(record):
                self.restore(record)
            elif record['phase'] == 'staged':
                if record.get('fingerprint') is not None and not self.verify_sources(record['fingerprint']):
                    self.restore(record)
                    raise ValueError('Netplan hierarchy changed before application')
                for name, change in record['files'].items():
                    if self.file(name) != change['before']:
                        self.restore(record)  # Nothing applied; retain the external edit.
                        raise ValueError('Netplan source changed before application')
                record['phase'] = 'applying'
                self.write(record)
                try:
                    for name, change in record['files'].items():
                        metadata = {**change['before'], 'mode': 0o600}
                        self.replace(name, change['after'], metadata)
                    self.apply()
                except Exception:
                    self.restore(record)
                    raise
                record['phase'] = 'pending'
                self.write(record)
            return self.public(record)

    def confirm(self, identifier, proof):
        result = self._confirm(identifier, proof)
        self.finalize()
        return result

    def _confirm(self, identifier, proof):
        with self.locked():
            record = self.read()
            if not record or record['id'] != identifier or record['phase'] != 'pending':
                raise ValueError('No matching pending network change')
            if self.expired(record):
                self.restore(record)
                raise ValueError('Network confirmation expired')
            if not self.verify_confirmation(proof, self.public(record)):
                raise ValueError('Confirmation must arrive through the new appliance address')
            for name, change in record['files'].items():
                if self.file(name)['bytes'] != change['after']:
                    raise ValueError('Netplan sources changed before confirmation')
            record['phase'] = 'confirmed'
            record.pop('files')
            record.pop('confirmation', None)
            self.write(record)
            return self.public(record)

    def cancel(self, identifier):
        result = self._cancel(identifier)
        self.finalize()
        return result

    def _cancel(self, identifier):
        with self.locked():
            record = self.read()
            if not record or record['id'] != identifier or record['phase'] in ('confirmed', 'rolled-back'):
                raise ValueError('No matching network change')
            self.restore(record)
            return self.public(record)
