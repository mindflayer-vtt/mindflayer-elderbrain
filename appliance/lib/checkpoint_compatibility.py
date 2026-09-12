"""Checkpoint runtime compatibility; no credentials are included in metadata."""
import hashlib
from pathlib import Path
import re
import subprocess

SERVICES = {'elderbrain-setup', 'mindflayer-server', 'foundry', 'traefik'}


def validate(value):
    if (not isinstance(value, dict) or set(value) != {'schema', 'applianceVersion', 'composeSha256', 'images'}
            or type(value['schema']) is not int or value['schema'] != 1
            or not isinstance(value['applianceVersion'], str)
            or not re.fullmatch(r'[A-Za-z0-9._+-]{1,128}', value['applianceVersion'])
            or not isinstance(value['composeSha256'], str)
            or not re.fullmatch(r'[a-f0-9]{64}', value['composeSha256'])
            or not isinstance(value['images'], dict)
            or set(value['images']) - SERVICES
            or any(not isinstance(image, str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', image)
                   for image in value['images'].values())):
        raise ValueError('Invalid checkpoint compatibility metadata')
    return value


def capture(runtime, *, run=subprocess.run):
    runtime = Path(runtime)
    command = ['docker', 'compose', '--env-file', str(runtime / 'appliance.env'),
               '-f', str(runtime / 'compose.yaml'), '--profile', 'foundry', 'ps', '-a', '-q']
    identifiers = run(command, check=True, capture_output=True, text=True, timeout=30).stdout.split()
    if any(not re.fullmatch(r'[a-f0-9]{12,64}', identifier) for identifier in identifiers):
        raise ValueError('Invalid runtime container identity')
    images = {}
    if identifiers:
        output = run(['docker', 'inspect', '--format',
                      '{{ index .Config.Labels "com.docker.compose.service" }} {{.Image}}', *identifiers],
                     check=True, capture_output=True, text=True, timeout=30).stdout
        for line in output.splitlines():
            service, image = line.split()
            if service in images:
                raise ValueError('Ambiguous runtime service image')
            images[service] = image
    return validate({'schema': 1, 'applianceVersion': (runtime / 'VERSION').read_text().strip(),
                     'composeSha256': hashlib.sha256((runtime / 'compose.yaml').read_bytes()).hexdigest(),
                     'images': images})


def require_compatible(archived, current, components):
    validate(archived)
    validate(current)
    if archived != current:
        raise ValueError('Checkpoint runtime differs; restore its compatible appliance release first')
    if 'foundry' in components and 'foundry' not in archived['images']:
        raise ValueError('Checkpoint has no verified Foundry runtime identity')
