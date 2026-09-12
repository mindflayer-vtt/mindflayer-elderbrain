"""Snapshot and validate Netplan candidates without changing live networking."""
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import yaml
from network_sources import rewrite
from network_transaction import NetworkTransaction


def prepare_restore(archived, root='/', validate=None):
    """Validate a complete archived /etc/netplan set without live mutations.

    Caller must verify/pin the checkpoint first. Returned configuration and file
    bytes are private; the coordinator derives address confirmation separately.
    Runtime/vendor Netplan layers remain those of the compatible installed OS.
    """
    validate = validate or netplan
    if not isinstance(archived, dict) or not 1 <= len(archived) <= 64:
        raise ValueError('Invalid archived Netplan file set')
    for name, content in archived.items():
        NetworkTransaction.filename(name)
        if not isinstance(content, bytes) or len(content) > 2 * 1024 * 1024:
            raise ValueError('Invalid archived Netplan file')
    before = snapshot(root)
    previous = {Path(name).name: value['content'] for name, value in before.items()
                if name.startswith('etc/netplan/')}
    with tempfile.TemporaryDirectory(prefix='elderbrain-network-restore-') as directory:
        stage = Path(directory)
        (stage / 'etc/netplan').mkdir(parents=True)
        for name, value in before.items():
            if name.startswith('etc/netplan/'):
                continue
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value['content'])
            target.chmod(0o600)
        for name, content in archived.items():
            target = stage / 'etc/netplan' / name
            target.write_bytes(content)
            target.chmod(0o600)
        validate(stage, 'generate')
        configuration = validate(stage, 'get')
        baseline = fingerprint(before)
        if fingerprint(snapshot(root)) != baseline:
            raise ValueError('Netplan sources changed during restore validation')
        changes = {name: {'before': previous.get(name), 'after': archived.get(name)}
                   for name in sorted(set(previous) | set(archived))
                   if previous.get(name) != archived.get(name)}
        if not changes or len(changes) > 64:
            raise ValueError('No network changes or too many changed sources')
        return {'changes': changes, 'fingerprint': baseline, 'configuration': configuration}


def snapshot(root='/'):
    result = {}
    for layer in ('lib', 'etc', 'run'):
        directory = Path(root) / layer / 'netplan'
        try:
            descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except FileNotFoundError:
            continue
        try:
            for name in sorted(os.listdir(descriptor)):
                if not name.endswith('.yaml'):
                    continue
                if len(result) >= 128:
                    raise ValueError('Too many Netplan source files')
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
                with os.fdopen(fd, 'rb') as source:
                    info = os.fstat(source.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size > 2 * 1024 * 1024:
                        raise ValueError('Invalid Netplan source')
                    content = source.read(2 * 1024 * 1024 + 1)
                    if len(content) > 2 * 1024 * 1024:
                        raise ValueError('Netplan source exceeds size limit')
                    result[f'{layer}/netplan/{name}'] = {'content': content, 'mode': stat.S_IMODE(info.st_mode),
                                                       'uid': info.st_uid, 'gid': info.st_gid}
        finally:
            os.close(descriptor)
    return result


def fingerprint(files):
    digest = hashlib.sha256()
    for name, source in sorted(files.items()):
        for value in (name.encode(), str(source['mode']).encode(), str(source['uid']).encode(),
                      str(source['gid']).encode(), source['content']):
            digest.update(len(value).to_bytes(8, 'big'))
            digest.update(value)
    return digest.hexdigest()


def netplan(root, operation):
    if operation not in ('get', 'generate'):
        raise ValueError('Only isolated Netplan validation is permitted')
    # Never include configuration values, credentials or raw Netplan errors in logs.
    result = subprocess.run(['netplan', operation, '--root-dir', str(root)], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError('Netplan rejected the candidate configuration')
    return yaml.safe_load(result.stdout) if operation == 'get' else None


def prepare(values, root='/', mac=None, validate=netplan):
    before = snapshot(root)
    with tempfile.TemporaryDirectory(prefix='elderbrain-network-stage-') as directory:
        stage = Path(directory)
        for name, source in before.items():
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source['content'])
            target.chmod(0o600)
        merged = validate(stage, 'get')
        candidate = rewrite({name: source['content'] for name, source in before.items()}, merged, values, mac)
        for name, change in candidate['files'].items():
            (stage / name).write_bytes(change['after'])
        validate(stage, 'generate')
        if validate(stage, 'get') != candidate['configuration']:
            raise ValueError('Netplan merged result differs from the requested configuration')
        baseline = fingerprint(before)
        if fingerprint(snapshot(root)) != baseline:
            raise ValueError('Netplan sources changed during validation; prepare the change again')
        return {'changes': {Path(name).name: change for name, change in candidate['files'].items()},
                'fingerprint': baseline, 'warnings': candidate['warnings']}
