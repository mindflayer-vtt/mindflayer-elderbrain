"""Durable code/image preparation, deliberately separate from live activation."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

from appliance_release import verify, verify_host, require_compatible
from release_compose import render
from release_images import prepare as prepare_images
from release_staging import stage, inventory


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def prepare(archive, manifest, signature, public_key, allowed_paths, *, directory,
            platform, configuration_schema, environment_file, allow_download=False, run=subprocess.run):
    release = verify(manifest, signature, public_key)
    require_compatible(release, platform=platform, configuration_schema=configuration_schema)
    paths = inventory(allowed_paths)
    if not {'runtime/VERSION', 'templates/compose.yaml'} <= set(paths) or 'runtime/compose.yaml' in paths:
        raise ValueError('Release inventory must separate templates from generated runtime configuration')
    directory = Path(directory)
    info = directory.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077
            or directory.resolve() != directory.absolute()):
        raise ValueError('Prepared releases require a private canonical parent')
    descriptor = os.open(directory / '.prepare.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        destination = directory / release['version']
        if destination.exists() or destination.is_symlink():
            raise FileExistsError('Release version already exists; inspect it rather than overwriting')
        # Bound host staging/copy overhead separately from registry image storage.
        # Docker disk-space preflight still belongs to the activation coordinator.
        if shutil.disk_usage(directory).free < 2 * 512 * 1024 ** 2 + release['host']['artifact']['size'] * 2:
            raise ValueError('Insufficient space for private host release preparation')
        with tempfile.TemporaryDirectory(prefix='.preparing-', dir=directory) as temporary:
            work = Path(temporary)
            prepared = work / 'prepared'
            prepared.mkdir(mode=0o700)
            with stage(archive, manifest, signature, public_key, paths, parent=work) as (checked, tree):
                if (tree / 'runtime/VERSION').read_text() != checked['host']['version'] + '\n':
                    raise ValueError('Host package version differs from signed manifest')
                images = prepare_images(manifest, signature, public_key, allow_download=allow_download, run=run)
                shutil.copytree(tree, prepared / 'tree')
                compose = prepared / 'tree/runtime/compose.yaml'
                compose.write_bytes(render((tree / 'templates/compose.yaml').read_bytes(), checked))
                # Config-only validation: never contact containers or write the
                # persistent environment file, even when explicit downloads ran.
                run(['docker', 'compose', '--env-file', str(environment_file), '-f', str(compose),
                     '--profile', 'foundry', 'config', '--quiet'], check=True,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
                # Retain the stager's exact authenticated compressed copy so a
                # future activator can reverify/re-extract, not trust a receipt alone.
                shutil.copyfile(tree.parent / 'host.tar.zst', prepared / 'elderbrain-host.tar.zst')
                verify_host(prepared / 'elderbrain-host.tar.zst', checked)
            (prepared / 'manifest.json').write_bytes(manifest)
            (prepared / 'manifest.sig').write_bytes(signature)
            receipt = {'state': 'code-and-images-prepared', 'version': release['version'],
                       'manifestSha256': hashlib.sha256(manifest).hexdigest(), 'images': images['images'],
                       'dependenciesPrepared': False, 'activationReady': False}
            (prepared / 'preparation.json').write_text(json.dumps(receipt, sort_keys=True))
            # Persist all generated files and directory entries before publication.
            for parent, _directories, files in os.walk(prepared, topdown=False):
                for name in files:
                    with (Path(parent) / name).open('rb') as stream:
                        os.fsync(stream.fileno())
                sync_directory(parent)
            os.rename(prepared, destination)  # Version absent under exclusive lock.
            sync_directory(directory)
        return receipt
    finally:
        os.close(descriptor)
