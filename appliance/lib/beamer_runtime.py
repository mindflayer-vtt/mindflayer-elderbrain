"""Root-owned, minimal Beamer credential projection for the kiosk account."""
import json
import os
from pathlib import Path
import pwd
import re
import stat
import tempfile
import fcntl
import math
import time

SOURCE = Path('/var/lib/mindflayer-elderbrain/elderbrain/secrets/beamer.json')
DIRECTORY = Path('/run/elderbrain-browser')
STATES = {'ready', 'unavailable', 'world-not-running', 'module-unavailable', 'pairing-required',
          'review-required', 'unsupported-version', 'origin-mismatch', 'login-failed', 'canvas-unavailable',
          'stopped', 'pending-verification'}


def public_status(value, revision, now):
    def fresh(timestamp):
        return isinstance(timestamp, (float, int)) and math.isfinite(timestamp) and -2 <= now - timestamp <= 15
    if not isinstance(value, dict) or not fresh(value.get('updatedAt')):
        return {'state': 'unavailable', 'views': []}
    entries = value.get('views')
    if not isinstance(entries, list) or len(entries) > 2:
        return {'state': 'unavailable', 'views': []}
    views = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get('index') not in (0, 1) or entry.get('state') not in STATES:
            return {'state': 'unavailable', 'views': []}
        state = entry['state']
        if entry.get('revision') != revision:
            state = 'pending-verification'
        elif state == 'ready' and not fresh(entry.get('observedAt')):
            state = 'unavailable'
        views.append({'index': entry['index'], 'state': state})
    if len({view['index'] for view in views}) != len(views):
        return {'state': 'unavailable', 'views': []}
    return {'state': next((view['state'] for view in views if view['state'] != 'ready'), 'ready') if views else 'display-disconnected',
            'views': views}


def status():
    value = read_private(SOURCE)
    if value is None:
        return {'state': 'pairing-required', 'views': []}
    uid = pwd.getpwnam('elderbrain-kiosk').pw_uid
    file = Path(f'/run/user/{uid}/beamer-status.json')
    try:
        descriptor = os.open(file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor) as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_mode & 0o077 or info.st_size > 4096:
                raise ValueError('Invalid worker status')
            return public_status(json.loads(stream.read(4097)), value['revision'], time.time())
    except (OSError, ValueError, TypeError):
        return {'state': 'unavailable', 'views': []}


def credential(value):
    if not isinstance(value, dict) or value.get('version') != 1:
        raise ValueError('Invalid Beamer record')
    patterns = {'revision': r'[a-f0-9]{32}', 'worldId': r'[A-Za-z0-9_-]{1,128}'}
    identity = 'username' if 'username' in value else 'userId'
    if identity == 'username':
        name = value['username']
        if not isinstance(name, str) or not name.strip() or len(name) > 128 or re.search(r'[\x00-\x1f\x7f]', name):
            raise ValueError('Invalid Beamer username')
    else:
        patterns['userId'] = r'[A-Za-z0-9]{16}'
    if any(not isinstance(value.get(key), str) or not re.fullmatch(pattern, value[key]) for key, pattern in patterns.items()):
        raise ValueError('Invalid Beamer record')
    secret = value.get('password')
    if not isinstance(secret, str) or not 12 <= len(secret) <= 256 or re.search(r'[\x00-\x1f\x7f]', secret):
        raise ValueError('Invalid Beamer record')
    return {key: value[key] for key in ('version', 'revision', 'worldId', identity, 'password')}


def read_private(file, owners=(0, 1000), mask=0o077):
    try:
        descriptor = os.open(file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 4096 or info.st_uid not in owners or info.st_mode & mask:
            raise ValueError('Unsafe Beamer record')
        with os.fdopen(descriptor, 'r', closefd=False) as stream:
            return credential(json.loads(stream.read(4097)))
    except Exception:
        raise ValueError('Beamer record unavailable') from None
    finally:
        os.close(descriptor)


def refresh(source=SOURCE, directory=DIRECTORY, group=None):
    group = pwd.getpwnam('elderbrain-kiosk').pw_gid if group is None else group
    directory.mkdir(mode=0o750, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise ValueError('Unsafe Beamer runtime directory')
    os.chown(directory, os.geteuid(), group)
    directory.chmod(0o750)
    lock = os.open(directory / '.beamer-lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            value = read_private(source)
        except Exception:
            (directory / 'beamer.json').unlink(missing_ok=True)
            raise
        if value is None:
            (directory / 'beamer.json').unlink(missing_ok=True)
            return {'state': 'pairing-required'}
        descriptor, temporary = tempfile.mkstemp(prefix='.beamer-', dir=directory)
        try:
            with os.fdopen(descriptor, 'w') as stream:
                os.fchown(stream.fileno(), os.geteuid(), group)
                os.fchmod(stream.fileno(), 0o640)
                json.dump(value, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, directory / 'beamer.json')
        finally:
            Path(temporary).unlink(missing_ok=True)
        return {'state': 'pending-verification'}
    finally:
        os.close(lock)
