"""Prepare an offline rollback baseline for a legacy installed container stack.

Local image IDs identify existing trusted installation bytes, not a new signed
release. This operation never starts containers or changes the live runtime.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import uuid

import yaml

from backup_service import save_record
from release_bootstrap import publish
from release_interlocks import update_admission, settings_admission
from release_prepare import sync_directory
from release_runtime import private_directory, read_regular
from restore_service import persistent_identity
from snapshot_service import stable_settings

SERVICES = {'elderbrain-setup', 'traefik', 'mindflayer-server', 'foundry'}
LOCAL_IMAGE = r'sha256:[a-f0-9]{64}'


def render(template, images):
    if not isinstance(template, bytes) or not 0 < len(template) <= 1024 ** 2:
        raise ValueError('Invalid baseline Compose size')
    document = yaml.safe_load(template)
    if (not isinstance(document, dict) or document.get('name') != 'mindflayer-elderbrain'
            or set(document) - {'name', 'services', 'networks', 'secrets', 'volumes'}
            or not isinstance(document.get('services'), dict) or set(document['services']) != SERVICES
            or set(images) != SERVICES):
        raise ValueError('Unexpected baseline Compose structure')
    generated = deepcopy(document)
    for name, service in generated['services'].items():
        if (not isinstance(service, dict) or 'extends' in service or 'develop' in service
                or not re.fullmatch(LOCAL_IMAGE, str(images[name]))):
            raise ValueError('Baseline requires direct services and immutable local image IDs')
        service.pop('build', None)
        service.update(image=images[name], pull_policy='never')
    return yaml.safe_dump(generated, sort_keys=False).encode()


def output(args, *, run, cwd):
    result = run(args, check=True, capture_output=True, text=True, timeout=60, cwd=cwd,
                 stdin=subprocess.DEVNULL,
                 env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'})
    if len(result.stdout) > 4 * 1024 ** 2:
        raise ValueError('Baseline inspection exceeds limit')
    return json.loads(result.stdout)


def prepare(runtime, *, state, directory, host_root=Path('/'), run=subprocess.run):
    runtime, state, host_root = map(Path, (runtime, state, host_root))
    identity = persistent_identity(state, host_root)
    if identity is None:
        raise ValueError('Offline baseline requires verified persistent storage')
    directory = private_directory(directory)
    if runtime.resolve() != runtime.absolute() or not runtime.is_dir():
        raise ValueError('Baseline runtime must be canonical')
    with update_admission(state), settings_admission(state), stable_settings(state):
        template = read_regular(runtime / 'compose.yaml', 1024 ** 2)
        # Validate structure before invoking Compose. Resolved settings exist
        # only in memory; never persist the environment-expanded document.
        render(template, {name: 'sha256:' + '0' * 64 for name in SERVICES})
        compose = ['docker', 'compose', '--project-directory', str(runtime),
                   '--env-file', str(runtime / 'appliance.env'), '--profile', 'foundry']
        resolved = output([*compose, '-f', str(runtime / 'compose.yaml'), 'config', '--format', 'json'],
                          run=run, cwd=runtime)
        services = resolved.get('services') if isinstance(resolved, dict) else None
        if not isinstance(services, dict) or set(services) != SERVICES:
            raise ValueError('Resolved baseline services differ')
        images = {}
        for name in sorted(SERVICES):
            service = services[name]
            reference = service.get('image') if isinstance(service, dict) else None
            if not isinstance(reference, str) or not reference or reference.startswith('-'):
                raise ValueError('Missing baseline image reference')
            records = output(['docker', 'image', 'inspect', reference], run=run, cwd=runtime)
            if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
                raise ValueError('Invalid baseline image inspection')
            image = records[0]
            if (not re.fullmatch(LOCAL_IMAGE, str(image.get('Id', '')))
                    or image.get('Os') != 'linux' or image.get('Architecture') != 'amd64'):
                raise ValueError('Baseline image identity or platform mismatch')
            images[name] = image['Id']
        generated = render(template, images)
        with tempfile.TemporaryDirectory(prefix='.baseline-', dir=directory) as temporary:
            work = Path(temporary)
            publish(work / 'compose.yaml', generated, 0o600)
            checked = output([*compose, '-f', str(work / 'compose.yaml'), 'config', '--format', 'json'],
                             run=run, cwd=runtime)
            expected = deepcopy(resolved)
            for name, service in expected['services'].items():
                service.pop('build', None)
                service.update(image=images[name], pull_policy='never')
            if checked != expected:
                raise ValueError('Offline baseline changes settings beyond image policy')
            if (persistent_identity(state, host_root) != identity
                    or read_regular(runtime / 'compose.yaml', 1024 ** 2) != template):
                raise ValueError('Baseline source or persistent storage changed')
            publish(work / 'previous-compose.yaml', template, 0o600)
            record = {'format': 1, 'state': 'baseline-prepared', 'activationReady': False,
                      'id': uuid.uuid4().hex, 'images': images,
                      'sourceSha256': hashlib.sha256(template).hexdigest(),
                      'composeSha256': hashlib.sha256(generated).hexdigest()}
            save_record(work / 'baseline.json', record)
            sync_directory(work)
            destination = directory / record['id']
            os.rename(work, destination)
            sync_directory(directory)
            return {**record, 'directory': str(destination)}
