"""Install explicitly baked-in update trust; refuse implicit key replacement."""
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'appliance/lib'))
from restore_service import persistent_identity
from release_catalog import trusted
from release_runtime import private_directory


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def provision(*, payload=ROOT, host_root=Path('/')):
    payload, root = Path(payload).absolute(), Path(host_root).absolute()
    source, key = [payload / 'config/private' / name for name in ('release-source.json', 'release-public.pem')]
    if not source.exists() and not key.exists():
        return {'state': 'not-configured'}
    config, public = module('release_input', ROOT / 'iso/validate-release.py').validate(source, key)
    state = root / 'var/lib/mindflayer-elderbrain'
    if persistent_identity(state, root) is None:
        raise ValueError('Update trust requires verified persistent storage')
    entries = module('release_inventory', ROOT / 'release/build-host.py').entries(payload / 'release/host-files.json')
    inventory = {entry['path']: entry['mode'] for entry in entries}
    inventory['runtime/VERSION'] = 0o644
    directory = root / 'etc/elderbrain'
    values = {'release-public.pem': public, 'release-source.json': json.dumps(config, sort_keys=True).encode(),
              'release-inventory.json': json.dumps(inventory, sort_keys=True).encode()}
    # Check every existing file before writing any. Re-provisioning cannot rotate
    # trust or quietly replace a reviewed inventory/source.
    for name, value in values.items():
        target = directory / name
        if target.exists() or target.is_symlink():
            existing = trusted(target, 1024 ** 2)
            same = existing == value if name.endswith('.pem') else json.loads(existing) == json.loads(value)
            if not same:
                raise ValueError('Existing update trust differs; explicit migration is required')
    for path in (root / 'var/lib/elderbrain-releases', root / 'var/lib/elderbrain-releases/prepared',
                 root / 'var/lib/elderbrain-releases/staging', root / 'usr/lib/elderbrain-dependencies'):
        path.mkdir(mode=0o700, exist_ok=True)
        private_directory(path)
    for name, value in values.items():
        target = directory / name
        if target.exists():
            continue
        with target.open('xb') as stream:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return {'state': 'configured'}


if __name__ == '__main__':
    if os.geteuid() != 0:
        raise SystemExit('Update trust provisioning requires root')
    print(json.dumps(provision()))
