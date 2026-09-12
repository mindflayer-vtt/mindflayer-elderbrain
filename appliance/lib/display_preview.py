"""Persistent, fail-closed display previews. Committed config changes only on confirmation."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time
from contextlib import contextmanager
from urllib.parse import urlsplit


def validate(candidate):
    from domain_routes import validate_domain
    if isinstance(candidate, dict):
        validate_domain(candidate.get('domain', 'elderbrain.local'))
    if not isinstance(candidate, dict) or not isinstance(candidate.get('configured'), bool):
        raise ValueError('Invalid display configuration')
    views = candidate.get('views')
    if not isinstance(views, list) or not 1 <= len(views) <= 2:
        raise ValueError('One or two views required')
    selected = set()
    for view in views:
        if not isinstance(view, dict):
            raise ValueError('Invalid view')
        output = view.get('output', '')
        if not isinstance(output, str) or (output and not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', output)):
            raise ValueError('Invalid output')
        if output and output in selected:
            raise ValueError('Duplicate output')
        selected.add(output)
        if view.get('mode', 'player') not in ('admin', 'player'):
            raise ValueError('Invalid browser mode')
        tabs = view.get('tabs', [])
        if not isinstance(tabs, list) or len(tabs) > 10:
            raise ValueError('Invalid additional tabs')
        for value in [view.get('url'), *tabs]:
            if not isinstance(value, str) or len(value) > 2048 or re.search(r'[\x00-\x20\x7f]', value):
                raise ValueError('Invalid browser URL')
            url = urlsplit(value)
            if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
                raise ValueError('Invalid browser URL')
    return json.loads(json.dumps(candidate))


def restart():
    subprocess.run(['systemctl', '--no-block', 'restart', 'elderbrain-graphics.service'],
                   check=True, capture_output=True, timeout=10)


class DisplayPreview:
    def __init__(self, state='/var/lib/mindflayer-elderbrain', clock=time.time, reboot_id=None, apply=restart, monotonic=time.monotonic):
        self.root = Path(state) / 'display-preview'
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.config = Path(state) / 'elderbrain/config.json'
        self.clock = clock
        self.monotonic = monotonic
        self.boot = reboot_id or Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        self.apply = apply

    @contextmanager
    def locked(self):
        with open(self.root / 'lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def read(self):
        try:
            return json.loads((self.root / 'state.json').read_text())
        except FileNotFoundError:
            return None

    def write(self, value):
        temporary = self.root / ('state-' + secrets.token_hex(8))
        with open(temporary, 'x') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.root / 'state.json')
        descriptor = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def current(self):
        try:
            parent = os.open(self.config.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        try:
            try:
                descriptor = os.open(self.config.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            except FileNotFoundError:
                return None
            with os.fdopen(descriptor, 'rb') as stream:
                return stream.read(65537)
        finally:
            os.close(parent)

    def commit(self, value):
        parent = os.open(self.config.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        temporary = '.display-' + secrets.token_hex(16)
        try:
            descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            with os.fdopen(descriptor, 'w') as stream:
                json.dump(value, stream)
                stream.flush()
                os.fsync(stream.fileno())
                if os.geteuid() == 0:
                    os.fchown(stream.fileno(), 1000, 1000)
            os.replace(temporary, self.config.name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass
            os.close(parent)

    @staticmethod
    def digest(value):
        return hashlib.sha256(value).hexdigest() if value is not None else None

    def expired(self, record):
        return record['boot'] != self.boot or self.clock() >= record['deadline'] or self.monotonic() >= record['expires']

    @staticmethod
    def public(record):
        return {key: record[key] for key in ('id', 'phase', 'deadline')} if record else {'phase': 'idle'}

    def rollback(self, record):
        record['phase'] = 'rolling-back'
        self.write(record)  # Projection immediately stops using the candidate.
        self.apply()
        record['phase'] = 'rolled-back'
        record.pop('candidate', None)
        self.write(record)

    def begin(self, candidate, seconds=90):
        candidate = validate(candidate)
        if not 15 <= seconds <= 180:
            raise ValueError('Invalid preview duration')
        with self.locked():
            previous = self.read()
            if previous and previous['phase'] in ('pending', 'rolling-back', 'committing'):
                raise ValueError('A display preview is already in progress')
            record = {'id': secrets.token_hex(16), 'phase': 'pending', 'deadline': self.clock() + seconds,
                      'expires': self.monotonic() + seconds, 'boot': self.boot, 'base': self.digest(self.current()), 'candidate': candidate}
            self.write(record)  # Persist rollback obligation before applying anything.
            try:
                self.apply()
            except Exception:
                self.rollback(record)
                raise
            return self.public(record)

    def confirm(self, identifier):
        with self.locked():
            record = self.read()
            if not record or record['id'] != identifier or record['phase'] != 'pending':
                raise ValueError('No matching pending preview')
            if self.expired(record):
                self.rollback(record)
                raise ValueError('Display preview expired')
            if self.digest(self.current()) != record['base']:
                self.rollback(record)
                raise ValueError('Configuration changed during preview; changes were not overwritten')
            record['phase'] = 'committing'
            self.write(record)
            self.commit(record['candidate'])
            from domain_routes import reconcile
            reconcile(self.root.parent)
            record['phase'] = 'confirmed'
            record.pop('candidate', None)
            self.write(record)
            return self.public(record)

    def cancel(self, identifier):
        with self.locked():
            record = self.read()
            if not record or record['id'] != identifier or record['phase'] not in ('pending', 'rolling-back'):
                raise ValueError('No matching pending preview')
            self.rollback(record)
            return self.public(record)

    def recover(self):
        with self.locked():
            from domain_routes import reconcile
            reconcile(self.root.parent)
            record = self.read()
            if record and (record['phase'] == 'rolling-back' or record['phase'] == 'pending' and self.expired(record)):
                self.rollback(record)
            elif record and record['phase'] == 'committing':
                # A crash during an explicitly confirmed commit may leave either version.
                # Never reapply an uncommitted candidate; restart using committed storage.
                current = self.current()
                if current is not None and json.loads(current) == record['candidate']:
                    record['phase'] = 'confirmed'
                    record.pop('candidate', None)
                    self.write(record)
                else:
                    self.rollback(record)
            return self.public(record)

    def effective(self):
        with self.locked():
            record = self.read()
            if record and record['phase'] == 'pending' and not self.expired(record):
                return record['candidate']
            value = self.current()
            return json.loads(value) if value is not None else {'configured': False}


if __name__ == '__main__':
    store = DisplayPreview()
    while True:
        try:
            store.recover()
        except Exception:
            print('Display preview recovery failed; retrying', flush=True)
        time.sleep(1)
