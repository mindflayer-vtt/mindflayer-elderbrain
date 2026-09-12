"""Signed coordinated release metadata; verification grants no install authority.

Trust comes from an independently installed public key, never the release itself.
The exact manifest bytes are signed using the existing OpenSSL SHA-256 scheme.
Package extraction/activation and migration remain separate privileged steps.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

MANIFEST_LIMIT = 65536
HOST_LIMIT = 8 * 1024 ** 3
VERSION = r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'
IMAGE = r'[a-z0-9][a-z0-9./_-]*(?::[A-Za-z0-9_.-]+)?@sha256:[a-f0-9]{64}'


def keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected.split()):
        raise ValueError('Unsupported release manifest fields')


def number(value, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError('Invalid release integer')


def pattern(value, expression):
    if not isinstance(value, str) or len(value) > 512 or not re.fullmatch(expression, value):
        raise ValueError('Invalid release version, image or digest')


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate release manifest field')
        result[key] = value
    return result


def validate(value):
    fields = 'format kind version platform host setup images configurationSchema notes downtimeSeconds'
    if isinstance(value, dict) and value.get('format') == 2:
        fields += ' dependencies'
    keys(value, fields)
    if type(value['format']) is not int or value['format'] not in (1, 2) or value['kind'] != 'mindflayer-elderbrain-release':
        raise ValueError('Unsupported appliance release format')
    pattern(value['version'], VERSION)
    keys(value['platform'], 'os release architecture')
    if value['platform'] != {'os': 'ubuntu', 'release': '26.04', 'architecture': 'amd64'}:
        raise ValueError('Unsupported appliance platform')
    keys(value['host'], 'version apiVersion artifact')
    pattern(value['host']['version'], VERSION)
    number(value['host']['apiVersion'], 1, 65535)
    artifact = value['host']['artifact']
    keys(artifact, 'file size sha256')
    if artifact['file'] != 'elderbrain-host.tar.zst':
        raise ValueError('Unsupported host artifact name')
    number(artifact['size'], 1, HOST_LIMIT)
    pattern(artifact['sha256'], r'[a-f0-9]{64}')
    keys(value['setup'], 'version image hostApi')
    pattern(value['setup']['version'], VERSION)
    pattern(value['setup']['image'], IMAGE)
    api = value['setup']['hostApi']
    keys(api, 'min max')
    number(api['min'], 1, 65535)
    number(api['max'], api['min'], 65535)
    if not api['min'] <= value['host']['apiVersion'] <= api['max']:
        raise ValueError('Setup does not support the coordinated host API')
    keys(value['images'], 'traefik mindflayer-server foundry')
    for image in value['images'].values():
        pattern(image, IMAGE)
    number(value['configurationSchema'], 1, 65535)
    number(value['downtimeSeconds'], 0, 86400)
    if not isinstance(value['notes'], str) or len(value['notes']) > 16000 or '\0' in value['notes']:
        raise ValueError('Invalid release notes')
    if value['format'] == 2:
        validate_dependencies(value['dependencies'])
    return value


def validate_dependencies(value):
    keys(value, 'artifact pythonAbi files')
    if value['pythonAbi'] != 'cp314':
        raise ValueError('Unsupported dependency Python ABI')
    artifact = value['artifact']
    keys(artifact, 'file size sha256')
    if artifact['file'] != 'elderbrain-dependencies.tar.zst':
        raise ValueError('Unsupported dependency artifact name')
    number(artifact['size'], 1, 512 * 1024 ** 2)
    pattern(artifact['sha256'], r'[a-f0-9]{64}')
    files = value['files']
    if not isinstance(files, dict) or not 3 <= len(files) <= 256 or 'dependencies.json' not in files:
        raise ValueError('Invalid dependency file inventory')
    wheel_count = node_count = total = 0
    for name, metadata in files.items():
        if not isinstance(name, str) or len(name) > 240:
            raise ValueError('Invalid dependency filename')
        if re.fullmatch(r'wheels/[A-Za-z0-9_][A-Za-z0-9_.+-]*\.whl', name):
            wheel_count += 1
        elif re.fullmatch(r'node/playwright-core-[0-9]+\.[0-9]+\.[0-9]+\.tgz', name):
            node_count += 1
        elif name != 'dependencies.json':
            raise ValueError('Unsupported dependency file scope')
        keys(metadata, 'size sha256')
        number(metadata['size'], 1, 64 * 1024 ** 2)
        pattern(metadata['sha256'], r'[a-f0-9]{64}')
        total += metadata['size']
    if not wheel_count or node_count != 1 or total > 256 * 1024 ** 2:
        raise ValueError('Invalid dependency archive contents')
    return value


def verify(manifest, signature, public_key):
    """Authenticate exact bytes before parsing; caller supplies pinned PEM key."""
    if not isinstance(manifest, bytes) or not 0 < len(manifest) <= MANIFEST_LIMIT:
        raise ValueError('Invalid release manifest size')
    if not isinstance(signature, bytes) or not 0 < len(signature) <= 1024:
        raise ValueError('Invalid release signature size')
    if not isinstance(public_key, bytes) or not 0 < len(public_key) <= 16384:
        raise ValueError('Invalid pinned release public key')
    with tempfile.TemporaryDirectory(prefix='elderbrain-release-verify-') as temporary:
        root = Path(temporary)
        for name, data in (('manifest.json', manifest), ('manifest.sig', signature), ('public.pem', public_key)):
            with (root / name).open('xb') as output:
                os.fchmod(output.fileno(), 0o600)
                output.write(data)
        result = subprocess.run(['openssl', 'dgst', '-sha256', '-verify', str(root / 'public.pem'),
            '-signature', str(root / 'manifest.sig'), str(root / 'manifest.json')],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        if result.returncode:
            raise ValueError('Release signature does not match the pinned appliance key')
    return validate(json.loads(manifest, object_pairs_hook=unique))


def verify_host(path, release):
    """Check regular host archive bytes without extracting or executing them."""
    return verify_artifact(path, release, 'host')


def verify_artifact(path, release, component):
    validate(release)
    if component not in ('host', 'dependencies') or component not in release:
        raise ValueError('Unsupported release artifact component')
    artifact = release[component]['artifact']
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size != artifact['size']:
            raise ValueError('Host artifact size or type mismatch')
        digest = hashlib.sha256()
        remaining = artifact['size']
        while remaining:
            chunk = source.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError('Truncated host artifact')
            remaining -= len(chunk)
            digest.update(chunk)
        if source.read(1) or digest.hexdigest() != artifact['sha256']:
            raise ValueError('Host artifact checksum mismatch')
    # Activation must stage/copy and verify again; the caller's path can change.
    return {'size': artifact['size'], 'sha256': artifact['sha256']}


def require_compatible(release, *, platform, configuration_schema, installed_host_api=None, setup_only=False):
    validate(release)
    number(configuration_schema, 1, 65535)
    if type(setup_only) is not bool:
        raise ValueError('Invalid release update mode')
    if release['platform'] != platform or release['configurationSchema'] != configuration_schema:
        raise ValueError('Release requires a supported platform and explicit schema migration')
    if setup_only:
        api = release['setup']['hostApi']
        if type(installed_host_api) is not int or not api['min'] <= installed_host_api <= api['max']:
            raise ValueError('Setup release is incompatible with the installed host API')
