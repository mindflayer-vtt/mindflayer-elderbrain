"""Private component staging from a verified, pinned read-only checkpoint.

The coordinator must hold maintenance/settings locks and quiesce writers before
calling this module. Source identity, schema compatibility and pin lifetime are
the coordinator's responsibility. This module never activates staged files.
"""
import json
import os
from pathlib import Path
import stat

from backup_archive import safe_link
from checkpoint_components import selection, preferences, keypad_settings
from local_snapshots import validate_retention
from restore_transaction import copy_owned, sync_directory

DEFAULT_CONFIG = {'version': 1, 'configured': False, 'domain': 'elderbrain.local',
                  'controllers': {}, 'views': [
                      {'output': '', 'url': 'https://foundry.elderbrain.local', 'mode': 'admin', 'tabs': []},
                      {'output': '', 'url': 'https://foundry.elderbrain.local', 'mode': 'player', 'tabs': []}]}
DEFAULT_KEYPADS = {'revision': 0, 'ssid': '', 'psk': '', 'serverHost': '', 'serverPort': 10443}


def network_files(checkpoint):
    """Read only the fixed persistent Netplan scope of a verified checkpoint.

    No fallback to live files or empty configuration. The caller retains the
    checkpoint pin while reading and keeps these credential-bearing bytes private.
    """
    from network_transaction import NetworkTransaction
    checkpoint = Path(checkpoint)
    if not checkpoint.is_absolute() or checkpoint.resolve() != checkpoint:
        raise ValueError('Checkpoint requires a canonical path')
    descriptor = os.open(checkpoint, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in ('host', 'netplan'):
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        result = {}
        for name in sorted(os.listdir(descriptor)):
            if not name.endswith('.yaml'):
                continue
            NetworkTransaction.filename(name)
            if len(result) >= 64:
                raise ValueError('Too many archived Netplan files')
            file = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
            with os.fdopen(file, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 2 * 1024 * 1024:
                    raise ValueError('Invalid archived Netplan source')
                content = stream.read(2 * 1024 * 1024 + 1)
                if len(content) > 2 * 1024 * 1024:
                    raise ValueError('Archived Netplan source exceeds limit')
                result[name] = content
        if not result:
            raise ValueError('Checkpoint contains no persistent Netplan configuration')
        return result
    finally:
        os.close(descriptor)


def read_json(root, relative, *, fallback, limit=1024 * 1024):
    """Do not follow links in any path segment, even within the checkpoint."""
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or '..' in parts:
        raise ValueError('Invalid component path')
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        file = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        with os.fdopen(file, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise ValueError('Invalid component JSON file')
            data = stream.read(limit + 1)
            if len(data) > limit:
                raise ValueError('Component JSON exceeds limit')
            return json.loads(data)
    except FileNotFoundError:
        return json.loads(json.dumps(fallback))
    finally:
        os.close(descriptor)


def check_foundry_tree(source):
    if source.is_symlink() or not source.is_dir():
        raise ValueError('Foundry checkpoint directory is missing or unsafe')
    for path in source.rglob('*'):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            safe_link('foundry/' + str(path.relative_to(source)), os.readlink(path))
        elif not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise ValueError('Unsupported file in Foundry checkpoint')


def stage(current, checkpoint, destination, components):
    selected = selection(components)
    if set(selected) - {'preferences', 'keypad-settings', 'foundry'}:
        raise ValueError('Selected component requires a dedicated restore coordinator')
    current, checkpoint, destination = map(Path, (current, checkpoint, destination))
    for path in (current, checkpoint, destination):
        if not path.is_absolute() or path.resolve() != path:
            raise ValueError('Component staging requires canonical paths without symlinks')
    # A fresh private staging directory is never an existing/live destination.
    destination.mkdir(mode=0o700)
    sources, targets = {}, {}

    def publish(key, target, value, *, uid=1000):
        file = destination / key
        with open(file, 'x') as stream:
            os.fchmod(stream.fileno(), 0o600)
            if os.geteuid() == 0:
                os.fchown(stream.fileno(), uid, uid)
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        sources[key], targets[key] = file, current / target

    if 'preferences' in selected:
        before = read_json(current, 'elderbrain/config.json', fallback=DEFAULT_CONFIG)
        archived = read_json(checkpoint, 'elderbrain/config.json', fallback=DEFAULT_CONFIG)
        publish('preferences', 'elderbrain/config.json', preferences(before, archived))
        policy = read_json(checkpoint, 'snapshots/.retention', fallback={'enabled': False, 'keep': 10}, limit=4096)
        publish('checkpoint-retention', 'snapshots/.retention', validate_retention(policy), uid=0)
    if 'keypad-settings' in selected:
        values = keypad_settings(
            read_json(current, 'elderbrain/secrets/keypad-settings.json', fallback=DEFAULT_KEYPADS),
            read_json(current, 'elderbrain/keypads.json', fallback={}),
            read_json(checkpoint, 'elderbrain/secrets/keypad-settings.json', fallback=DEFAULT_KEYPADS),
            read_json(checkpoint, 'elderbrain/keypads.json', fallback={}))
        for key, relative in [('settings', 'elderbrain/secrets/keypad-settings.json'),
                              ('records', 'elderbrain/keypads.json'),
                              ('expectations', 'elderbrain/secrets/keypad-expectations.json')]:
            publish('keypad-' + key, relative, values[key])
    if 'foundry' in selected:
        source = checkpoint / 'foundry'
        check_foundry_tree(source)
        copy_owned(source, destination / 'foundry')
        sources['foundry'], targets['foundry'] = destination / 'foundry', current / 'foundry'
    sync_directory(destination)
    return sources, targets
