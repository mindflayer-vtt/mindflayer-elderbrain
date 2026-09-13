"""Fetch confirmed signed artifacts into private preparation, never live paths."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time

from appliance_release import unique, verify, require_compatible, validate
from release_catalog import source_url, trusted, fetch, open_release
from release_prepare import prepare


def artifact(base, release, component, directory):
    validate(release)
    if component not in ('host', 'dependencies'):
        raise ValueError('Unsupported artifact')
    selected = release[component]['artifact']
    source_url(base)
    connection, response = open_release(base, selected['file'], 30)
    destination = Path(directory) / selected['file']
    deadline = time.monotonic() + 1800
    try:
        if response.status != 200 or response.getheader('Content-Encoding', 'identity') != 'identity':
            raise ValueError('Release source did not serve artifact bytes over HTTPS')
        size = response.getheader('Content-Length')
        if size is not None and (not size.isdecimal() or int(size) != selected['size']):
            raise ValueError('Artifact length differs from signed release')
        digest = hashlib.sha256()
        remaining = selected['size']
        with destination.open('xb') as output:
            os.fchmod(output.fileno(), 0o600)
            while remaining:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Artifact download exceeded deadline')
                chunk = response.read1(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError('Truncated release artifact')
                output.write(chunk)
                digest.update(chunk)
                remaining -= len(chunk)
            if response.read(1) or digest.hexdigest() != selected['sha256']:
                raise ValueError('Artifact checksum or length differs from signed release')
            output.flush()
            os.fsync(output.fileno())
        return destination
    finally:
        connection.close()


def download_prepare(selected, key, paths, *, root, releases, dependencies, current, progress):
    config = json.loads(trusted(root / 'etc/elderbrain/release-source.json', 4096), object_pairs_hook=unique)
    if not isinstance(config, dict) or set(config) != {'baseUrl'}:
        raise ValueError('Invalid release source configuration')
    base = config['baseUrl']
    source_url(base)
    manifest, signature = fetch(base, 'manifest.json', 65536), fetch(base, 'manifest.sig', 1024)
    if hashlib.sha256(manifest).hexdigest() != selected['manifestSha256']:
        raise ValueError('Release changed after user confirmation; check for updates again')
    release = verify(manifest, signature, key)
    require_compatible(release, platform=current, configuration_schema=1)
    if release['format'] != 2 or release['version'] != selected['version']:
        raise ValueError('Download requires the confirmed complete release')
    required = sum(release[name]['artifact']['size'] for name in ('host', 'dependencies'))
    if shutil.disk_usage(releases).free < required * 3 + 1024 ** 3:
        raise ValueError('Insufficient space for release download and preparation')
    with tempfile.TemporaryDirectory(prefix='.download-', dir=releases) as temporary:
        progress('downloading-host')
        host = artifact(base, release, 'host', temporary)
        progress('downloading-dependencies')
        dependency = artifact(base, release, 'dependencies', temporary)
        progress('preparing-runtime')
        return prepare(host, manifest, signature, key, paths, directory=releases / 'prepared',
                       platform=current, configuration_schema=1,
                       environment_file=root / 'opt/mindflayer-elderbrain/appliance.env', allow_download=True,
                       dependency_archive=dependency, dependency_directory=dependencies)
