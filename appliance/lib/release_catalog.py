"""Read-only signed release discovery from an independently configured origin."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import platform
import re
import ssl
import stat
from urllib.parse import urlsplit

from appliance_release import VERSION, unique, verify, require_compatible
from release_recovery_bundle import active as active_recovery


def trusted(path, limit):
    path = Path(path)
    if path.resolve() != path.absolute():
        raise ValueError('Release configuration must be canonical')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o022 or not 0 < info.st_size <= limit):
            raise ValueError('Release configuration must be installer-owned and bounded')
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Release configuration exceeds limit')
    return data


def source_url(value):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(char) <= 32 or ord(char) >= 127 for char in value):
        raise ValueError('Invalid release source URL')
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment
            or not parsed.path.endswith('/') or '\\' in value):
        raise ValueError('Release source requires an HTTPS directory without credentials or query')
    _ = parsed.port  # Reject malformed ports before making a connection.
    return parsed


def fetch(base, filename, limit):
    parsed = source_url(base)
    if filename not in ('manifest.json', 'manifest.sig'):
        raise ValueError('Unsupported release metadata')
    connection = http.client.HTTPSConnection(parsed.hostname, parsed.port, timeout=10,
                                              context=ssl.create_default_context())
    try:
        connection.request('GET', parsed.path + filename, headers={'Accept-Encoding': 'identity'})
        response = connection.getresponse()
        if response.status != 200 or response.getheader('Content-Encoding', 'identity') != 'identity':
            raise ValueError('Release source must serve metadata directly over HTTPS')
        length = response.getheader('Content-Length')
        if length is not None and (not length.isdecimal() or not 0 < int(length) <= limit):
            raise ValueError('Release metadata exceeds limit')
        data = response.read(limit + 1)
        if not 0 < len(data) <= limit or (length is not None and len(data) != int(length)):
            raise ValueError('Invalid release metadata length')
        return data
    finally:
        connection.close()


def check(*, host_root=Path('/'), download=fetch):
    root = Path(host_root).absolute()
    installed = trusted(root / 'opt/mindflayer-elderbrain/VERSION', 129).decode().strip()
    if not re.fullmatch(VERSION, installed):
        raise ValueError('Invalid installed host version')
    result = {'installedHostVersion': installed, 'state': 'not-configured', 'release': None}
    config = root / 'etc/elderbrain/release-source.json'
    if not config.exists() and not config.is_symlink():
        return result
    selected = json.loads(trusted(config, 4096), object_pairs_hook=unique)
    if not isinstance(selected, dict) or set(selected) != {'baseUrl'}:
        raise ValueError('Invalid release source configuration')
    source_url(selected['baseUrl'])
    key = trusted(root / 'etc/elderbrain/release-public.pem', 16384)
    manifest = download(selected['baseUrl'], 'manifest.json', 65536)
    signature = download(selected['baseUrl'], 'manifest.sig', 1024)
    release = verify(manifest, signature, key)
    target = platform.freedesktop_os_release()
    current = {'os': target.get('ID'), 'release': target.get('VERSION_ID'),
               'architecture': 'amd64' if platform.machine() == 'x86_64' else platform.machine()}
    compatible = release['format'] == 2
    try:
        require_compatible(release, platform=current, configuration_schema=1)
        if active_recovery(directory=root / 'usr/lib/elderbrain-recovery')['recoveryApi'] != release['recoveryApi']:
            compatible = False
    except ValueError:
        compatible = False
    result.update(state='checked', release={
        'version': release['version'], 'hostVersion': release['host']['version'],
        'setupVersion': release['setup']['version'], 'notes': release['notes'],
        'recoveryApi': release['recoveryApi'],
        'downtimeSeconds': release['downtimeSeconds'], 'compatible': compatible,
        'manifestSha256': hashlib.sha256(manifest).hexdigest(),
    })
    return result
