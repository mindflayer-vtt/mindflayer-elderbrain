"""Persistent update worker for an explicitly confirmed, already prepared release."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess

from appliance_release import unique, verify, require_compatible
from release_apply import activate
from release_bootstrap import install
from release_runtime import private_directory, read_regular
from release_staging import inventory, stage
from restore_service import persistent_identity
from update_request import request


def trusted_file(path, limit):
    info = path.lstat()
    if path.resolve() != path or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise ValueError('Update trust configuration is not installer-owned')
    return read_regular(path, limit)


def run_update(state, identity, selected, *, progress, host_root=Path('/')):
    selected = request(selected)
    root, state = Path(host_root).absolute(), Path(state).absolute()
    if state != root / 'var/lib/mindflayer-elderbrain' or persistent_identity(state, root) is None:
        raise ValueError('Update worker requires fixed verified persistent storage')
    progress('verifying-release')
    paths = inventory(json.loads(trusted_file(root / 'etc/elderbrain/release-inventory.json', 1024 ** 2),
                                 object_pairs_hook=unique))
    key = trusted_file(root / 'etc/elderbrain/release-public.pem', 65536)
    releases = private_directory(root / 'var/lib/elderbrain-releases')
    prepared = private_directory(private_directory(releases / 'prepared') / selected['version'])
    staging = private_directory(releases / 'staging')
    dependencies = private_directory(root / 'usr/lib/elderbrain-dependencies')
    manifest = read_regular(prepared / 'manifest.json', 65536)
    if hashlib.sha256(manifest).hexdigest() != selected['manifestSha256']:
        raise ValueError('Release changed after user confirmation')
    signature = read_regular(prepared / 'manifest.sig', 1024)
    release = verify(manifest, signature, key)
    target = platform.freedesktop_os_release()
    current = {'os': target.get('ID'), 'release': target.get('VERSION_ID'),
               'architecture': 'amd64' if platform.machine() == 'x86_64' else platform.machine()}
    require_compatible(release, platform=current, configuration_schema=1)
    if release['format'] != 2 or release['version'] != selected['version']:
        raise ValueError('Update requires the confirmed complete release')
    with stage(prepared / 'elderbrain-host.tar.zst', manifest, signature, key, paths, parent=staging) as (_, tree):
        progress('preparing-recovery')
        install(tree, paths, state=state, host_root=root, job_owner=identity)
        subprocess.run(['systemctl', 'daemon-reload'], check=True, stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        progress('activating')
        return activate(prepared, key, paths, dependency_directory=dependencies, bootstrap_tree=tree,
                        platform=current, configuration_schema=1, parent=staging, host_root=root, job_owner=identity,
                        expected_manifest_sha256=selected['manifestSha256'])
