"""Durable code/image preparation, deliberately separate from live activation."""
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

from appliance_release import verify, verify_host, verify_artifact, require_compatible, unique
from release_compose import render
from release_images import prepare as prepare_images
from release_staging import stage, inventory


DEPENDENCY_INPUTS = {
    'config/defaults/serial-requirements.txt': 'dependencies/serial-requirements.txt',
    'config/defaults/borgmatic-requirements.txt': 'dependencies/borgmatic-requirements.txt',
    'provisioning/graphics/package-lock.json': 'runtime/beamer/package-lock.json',
}


def check_dependency_inputs(dependencies, host, release):
    index = dependencies / 'dependencies.json'
    if index.stat().st_size > 65536:
        raise ValueError('Dependency build receipt is too large')
    receipt = json.loads(index.read_bytes(), object_pairs_hook=unique)
    if (not isinstance(receipt, dict) or type(receipt.get('format')) is not int
            or receipt['format'] != 1 or receipt.get('platform') != release['platform']
            or not re.fullmatch(r'3\.14\.[0-9]+', str(receipt.get('python', '')))):
        raise ValueError('Dependency build target differs from host release')
    expected_files = {name: value for name, value in release['dependencies']['files'].items()
                      if name != 'dependencies.json'}
    if receipt.get('files') != expected_files:
        raise ValueError('Dependency receipt differs from signed inventory')
    expected_inputs = {source: hashlib.sha256((host / target).read_bytes()).hexdigest()
                       for source, target in DEPENDENCY_INPUTS.items()}
    if receipt.get('inputs') != expected_inputs:
        raise ValueError('Dependency inputs differ from host requirement files or browser lockfile')


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def prepare(archive, manifest, signature, public_key, allowed_paths, *, directory,
            platform, configuration_schema, environment_file, allow_download=False,
            dependency_archive=None, dependency_directory=None, run=subprocess.run):
    release = verify(manifest, signature, public_key)
    require_compatible(release, platform=platform, configuration_schema=configuration_schema)
    if ('dependencies' in release) != (dependency_archive is not None):
        raise ValueError('Dependency archive must be supplied exactly when signed by the release')
    if dependency_directory is not None and dependency_archive is None:
        raise ValueError('Offline installation requires signed dependency inputs')
    paths = inventory(allowed_paths)
    if not {'runtime/VERSION', 'templates/compose.yaml'} <= set(paths) or 'runtime/compose.yaml' in paths:
        raise ValueError('Release inventory must separate templates from generated runtime configuration')
    directory = Path(directory)
    info = directory.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077
            or directory.resolve() != directory.absolute()):
        raise ValueError('Prepared releases require a private canonical parent')
    if dependency_directory is not None:
        dependency_directory = Path(dependency_directory).absolute()
        if (dependency_directory.is_relative_to(directory.absolute())
                or directory.absolute().is_relative_to(dependency_directory)):
            raise ValueError('Stable dependency prefixes must be separate from prepared release trees')
    descriptor = os.open(directory / '.prepare.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        destination = directory / release['version']
        if destination.exists() or destination.is_symlink():
            raise FileExistsError('Release version already exists; inspect it rather than overwriting')
        # Bound host staging/copy overhead separately from registry image storage.
        # Docker disk-space preflight still belongs to the activation coordinator.
        artifact_size = release['host']['artifact']['size'] + release.get('dependencies', {}).get('artifact', {}).get('size', 0)
        if shutil.disk_usage(directory).free < 2 * 512 * 1024 ** 2 + artifact_size * 2:
            raise ValueError('Insufficient space for private host release preparation')
        with tempfile.TemporaryDirectory(prefix='.preparing-', dir=directory) as temporary:
            work = Path(temporary)
            prepared = work / 'prepared'
            prepared.mkdir(mode=0o700)
            installed = None
            with stage(archive, manifest, signature, public_key, paths, parent=work) as (checked, tree):
                if (tree / 'runtime/VERSION').read_text() != checked['host']['version'] + '\n':
                    raise ValueError('Host package version differs from signed manifest')
                if dependency_archive is not None:
                    with stage(dependency_archive, manifest, signature, public_key,
                               parent=work, component='dependencies') as (_, dependencies):
                        check_dependency_inputs(dependencies, tree, checked)
                        shutil.copytree(dependencies, prepared / 'dependency-inputs')
                        retained = prepared / 'elderbrain-dependencies.tar.zst'
                        shutil.copyfile(dependencies.parent / 'dependencies.tar.zst', retained)
                        verify_artifact(retained, checked, 'dependencies')
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
                if dependency_directory is not None:
                    # Import here: the standalone installer reuses the input
                    # binding checks above, but preparation never runs on import.
                    from release_dependencies import install
                    installed = install(prepared / 'elderbrain-host.tar.zst',
                        prepared / 'elderbrain-dependencies.tar.zst', manifest, signature,
                        public_key, paths, directory=dependency_directory,
                        configuration_schema=configuration_schema, run=run)
                    prefix = dependency_directory / release['version']
                    if (installed.get('manifestSha256') != hashlib.sha256(manifest).hexdigest()
                            or installed.get('version') != release['version']
                            or installed.get('prefix') != str(prefix)
                            or installed.get('dependenciesPrepared') is not True):
                        raise ValueError('Offline installer did not complete this release')
                    for name, target in {'serial-venv': prefix / 'serial-venv',
                                         'borgmatic-venv': prefix / 'borgmatic-venv',
                                         'beamer/node_modules': prefix / 'beamer/node_modules'}.items():
                        # Stable absolute links survive code-tree publication and
                        # activation; the dependency prefix itself is never moved.
                        os.symlink(str(target), prepared / 'tree/runtime' / name)
            (prepared / 'manifest.json').write_bytes(manifest)
            (prepared / 'manifest.sig').write_bytes(signature)
            receipt = {'state': 'runtime-prepared' if installed else 'code-and-images-prepared', 'version': release['version'],
                       'manifestSha256': hashlib.sha256(manifest).hexdigest(), 'images': images['images'],
                       'dependencyInputsVerified': dependency_archive is not None,
                       'dependenciesPrepared': installed is not None, 'activationReady': False}
            if installed:
                receipt['dependencyPrefix'] = installed['prefix']
            (prepared / 'preparation.json').write_text(json.dumps(receipt, sort_keys=True))
            # Persist all generated files and directory entries before publication.
            for parent, _directories, files in os.walk(prepared, topdown=False):
                for name in files:
                    file = Path(parent) / name
                    if file.is_symlink():
                        continue
                    with file.open('rb') as stream:
                        os.fsync(stream.fileno())
                sync_directory(parent)
            os.rename(prepared, destination)  # Version absent under exclusive lock.
            sync_directory(directory)
        return receipt
    finally:
        os.close(descriptor)
