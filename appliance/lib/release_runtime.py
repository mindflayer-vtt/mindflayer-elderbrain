"""Reconstruct an activation candidate from authenticated archives, not loose code."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

from appliance_release import verify, require_compatible, unique
from release_compose import render
from release_dependencies import pinned_requirements
from release_images import prepare as check_images
from release_prepare import check_dependency_inputs
from release_staging import stage
from restore_service import persistent_identity


def read_regular(path, limit):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
            raise ValueError('Invalid release metadata file')
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise ValueError('Release metadata exceeds limit')
    return value


def private_directory(path):
    path = Path(path).absolute()
    info = path.lstat()
    if (path.resolve() != path or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid() or info.st_mode & 0o077):
        raise ValueError('Runtime verification requires private canonical directories')
    return path


@contextmanager
def candidate(prepared, public_key, allowed_paths, *, dependency_directory, state,
              platform, configuration_schema, parent, host_root=Path('/'), run=subprocess.run):
    prepared = private_directory(prepared)
    state = Path(state).absolute()
    identity = persistent_identity(state, host_root)
    if identity is None:
        raise ValueError('Activation requires verified persistent storage')
    manifest = read_regular(prepared / 'manifest.json', 65536)
    signature = read_regular(prepared / 'manifest.sig', 1024)
    release = verify(manifest, signature, public_key)
    require_compatible(release, platform=platform, configuration_schema=configuration_schema)
    if release['format'] != 2 or prepared.name != release['version']:
        raise ValueError('Activation candidate must be a complete versioned release')
    prefix = private_directory(private_directory(dependency_directory) / release['version'])
    receipt = json.loads(read_regular(prefix / 'installation.json', 65536), object_pairs_hook=unique)
    if (not isinstance(receipt, dict) or receipt.get('state') != 'dependencies-installed'
            or receipt.get('version') != release['version'] or receipt.get('prefix') != str(prefix)
            or receipt.get('manifestSha256') != hashlib.sha256(manifest).hexdigest()
            or receipt.get('dependenciesPrepared') is not True):
        raise ValueError('Dependency installation does not belong to the signed release')
    with stage(prepared / 'elderbrain-host.tar.zst', manifest, signature, public_key,
               allowed_paths, parent=parent) as (_, tree), \
            stage(prepared / 'elderbrain-dependencies.tar.zst', manifest, signature, public_key,
                  parent=parent, component='dependencies') as (_, inputs):
        if (tree / 'runtime/VERSION').read_text() != release['host']['version'] + '\n':
            raise ValueError('Host version differs from signed release')
        check_dependency_inputs(inputs, tree, release)
        # Recheck installed runtime behavior; a completion receipt alone is not
        # proof that an environment is still present, complete or compatible.
        def offline(command):
            run(['unshare', '--net', '--', *map(str, command)], check=True,
                env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8',
                     'HOME': str(tree.parent), 'PIP_CONFIG_FILE': '/dev/null'}, cwd=tree.parent,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        for name in ('serial', 'borgmatic'):
            expected = pinned_requirements(tree / 'dependencies' / (name + '-requirements.txt'))
            python = prefix / (name + '-venv/bin/python')
            offline([python, '-I', '-m', 'pip', '--isolated', 'check'])
            offline([python, '-I', '-c', 'import importlib.metadata as m,json,sys; '
                     'assert all(m.version(k)==v for k,v in json.loads(sys.argv[1]).items())', json.dumps(expected)])
        offline([prefix / 'serial-venv/bin/python', '-I', '-c', 'import esptool'])
        offline([prefix / 'borgmatic-venv/bin/borgmatic', '--version'])
        lock = json.loads((tree / 'runtime/beamer/package-lock.json').read_text(), object_pairs_hook=unique)
        offline(['/usr/bin/node', '-e', 'const p=require(process.argv[1]); '
                 'if(!p.chromium||require(process.argv[1]+"/package.json").version!==process.argv[2])process.exit(1)',
                 prefix / 'beamer/node_modules/playwright-core', lock['packages']['node_modules/playwright-core']['version']])
        check_images(manifest, signature, public_key, allow_download=False, run=run)
        runtime = tree / 'runtime'
        (runtime / 'compose.yaml').write_bytes(render((tree / 'templates/compose.yaml').read_bytes(), release))
        links = {'serial-venv': prefix / 'serial-venv', 'borgmatic-venv': prefix / 'borgmatic-venv',
                 'beamer/node_modules': prefix / 'beamer/node_modules'}
        for name in ('appliance.env', 'sway.conf'):
            setting = state / 'host/runtime' / name
            if setting.resolve() != setting or not stat.S_ISREG(setting.lstat().st_mode):
                raise ValueError('Persistent runtime setting is missing or unsafe')
            links[name] = setting
        for name, target in links.items():
            os.symlink(str(target), runtime / name)  # Collision fails; never overwrite signed files.
        run(['docker', 'compose', '--env-file', str(runtime / 'appliance.env'), '-f', str(runtime / 'compose.yaml'),
             '--profile', 'foundry', 'config', '--quiet'], check=True, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        if persistent_identity(state, host_root) != identity:
            raise ValueError('Persistent storage changed during runtime verification')
        yield release, tree
