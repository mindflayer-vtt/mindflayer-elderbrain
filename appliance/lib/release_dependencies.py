"""Install authenticated offline inputs at their final, non-relocatable prefix."""
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile

from appliance_release import verify, require_compatible, unique
from release_prepare import check_dependency_inputs, sync_directory
from release_staging import stage


def pinned_requirements(path):
    pins = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)', line)
        if not match:
            raise ValueError('Offline installation requires exact runtime pins')
        name = re.sub(r'[-_.]+', '-', match[1]).lower()
        if name in pins:
            raise ValueError('Duplicate runtime dependency pin')
        pins[name] = match[2]
    if not pins:
        raise ValueError('Empty runtime dependency set')
    return pins


def install(archive, dependency_archive, manifest, signature, public_key, allowed_paths,
            *, directory, configuration_schema, run=subprocess.run):
    release = verify(manifest, signature, public_key)
    target = platform.freedesktop_os_release()
    current = {'os': target.get('ID'), 'release': target.get('VERSION_ID'),
               'architecture': 'amd64' if platform.machine() == 'x86_64' else platform.machine()}
    require_compatible(release, platform=current, configuration_schema=configuration_schema)
    if 'dependencies' not in release or sys.version_info[:2] != (3, 14):
        raise ValueError('Offline installation requires format 2 and Python 3.14')
    directory = Path(directory)
    info = directory.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o077 or directory.resolve() != directory.absolute()):
        raise ValueError('Dependency installation requires a private canonical parent')
    destination = directory / release['version']
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('Dependency prefix already exists; never overwrite or relocate environments')
    if shutil.disk_usage(directory).free < 2 * 1024 ** 3:
        raise ValueError('Insufficient space for offline dependency installation')
    with tempfile.TemporaryDirectory(prefix='.dependency-stage-', dir=directory) as temporary:
        work = Path(temporary)
        with stage(archive, manifest, signature, public_key, allowed_paths, parent=work) as (_, host), \
                stage(dependency_archive, manifest, signature, public_key,
                      parent=work, component='dependencies') as (_, dependencies):
            if (host / 'runtime/VERSION').read_text() != release['host']['version'] + '\n':
                raise ValueError('Host package version differs from signed manifest')
            check_dependency_inputs(dependencies, host, release)
            pins = {name: pinned_requirements(host / 'dependencies' / (name + '-requirements.txt'))
                    for name in ('serial', 'borgmatic')}
            lock = json.loads((host / 'runtime/beamer/package-lock.json').read_bytes(), object_pairs_hook=unique)
            if set(lock['packages']) != {'', 'node_modules/playwright-core'}:
                raise ValueError('Unsupported browser dependency graph')
            browser = lock['packages']['node_modules/playwright-core']
            version = browser['version']
            if not isinstance(version, str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
                raise ValueError('Invalid browser dependency version')
            node_archive = dependencies / 'node' / ('playwright-core-' + version + '.tgz')
            integrity = 'sha512-' + base64.b64encode(hashlib.sha512(node_archive.read_bytes()).digest()).decode()
            if browser['integrity'] != integrity:
                raise ValueError('Browser archive differs from host lock integrity')
            # mkdir is the exclusive claim. Failed/interrupted prefixes remain for
            # inspection, with no readiness marker; they are never renamed/reused.
            destination.mkdir(mode=0o700)
            sync_directory(directory)
            # npm rejects using one pathname for both configuration scopes.
            for name in ('npm-user.conf', 'npm-global.conf'):
                (work / name).touch(mode=0o600, exist_ok=False)
            environment = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'HOME': str(work),
                           'LANG': 'C.UTF-8', 'PIP_CONFIG_FILE': '/dev/null',
                           'npm_config_cache': str(work / 'npm-cache'),
                           'npm_config_userconfig': str(work / 'npm-user.conf'),
                           'npm_config_globalconfig': str(work / 'npm-global.conf')}

            def execute(command):
                return run(['unshare', '--net', '--', *map(str, command)], check=True,
                           cwd=work, env=environment, stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)

            for name, expected in pins.items():
                prefix = destination / (name + '-venv')
                execute(['/usr/bin/python3', '-I', '-m', 'venv', prefix])
                python = prefix / 'bin/python'
                execute([python, '-I', '-m', 'pip', '--isolated', 'install', '--no-index',
                         '--no-deps', '--only-binary=:all:', '--no-cache-dir', '--find-links',
                         dependencies / 'wheels', '-r', host / 'dependencies' / (name + '-requirements.txt')])
                execute([python, '-I', '-m', 'pip', '--isolated', 'check'])
                execute([python, '-I', '-c',
                         'import importlib.metadata as m,json,sys; '
                         'expected=json.loads(sys.argv[1]); '
                         'assert all(m.version(k)==v for k,v in expected.items())', json.dumps(expected)])
            execute([destination / 'serial-venv/bin/python', '-I', '-c', 'import esptool'])
            execute([destination / 'borgmatic-venv/bin/borgmatic', '--version'])
            browser_prefix = destination / 'beamer'
            browser_prefix.mkdir(mode=0o700)
            execute(['/usr/bin/npm', 'install', '--offline', '--ignore-scripts', '--omit=dev',
                     '--no-audit', '--no-fund', '--prefix', browser_prefix, node_archive])
            execute(['/usr/bin/node', '-e',
                     'const p=require(process.argv[1]); const v=require(process.argv[1]+"/package.json").version; '
                     'if (!p.chromium || v!==process.argv[2]) process.exit(1)',
                     browser_prefix / 'node_modules/playwright-core', version])
            receipt = {'state': 'dependencies-installed', 'version': release['version'],
                       'manifestSha256': hashlib.sha256(manifest).hexdigest(),
                       'prefix': str(destination), 'dependenciesPrepared': True, 'activationReady': False}
            # Persist installed files before publishing the completion marker.
            for parent, _directories, files in os.walk(destination, topdown=False):
                for name in files:
                    file = Path(parent) / name
                    if not file.is_symlink():
                        with file.open('rb') as stream:
                            os.fsync(stream.fileno())
                sync_directory(parent)
            pending = destination / '.installation.json'
            with pending.open('x') as stream:
                json.dump(receipt, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.rename(pending, destination / 'installation.json')
            sync_directory(destination)
            return receipt
