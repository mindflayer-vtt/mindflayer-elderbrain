"""Install recovery prerequisites from the trusted ISO provisioning payload.

This entry point shares the installer's trust boundary, not the online updater's:
it must never be pointed at a downloaded, unauthenticated release directory.
"""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'appliance/lib'))
from release_bootstrap import existing, files, install


def provision(*, host_root=Path('/')):
    # Use the same reviewed inventory parser as the host release packager.
    spec = importlib.util.spec_from_file_location('bootstrap_inventory', ROOT / 'release/build-host.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    entries = builder.entries(ROOT / 'release/host-files.json')
    required = set(files().values())
    selected = [entry for entry in entries if entry['path'] in required or
                (Path(entry['path']).parent == Path('runtime') and entry['path'].endswith('.py'))]
    if not required <= {entry['path'] for entry in selected}:
        raise ValueError('Provisioning payload lacks recovery prerequisites')
    with tempfile.TemporaryDirectory(prefix='elderbrain-recovery-source-') as temporary:
        tree = Path(temporary)
        for entry in selected:
            source = ROOT / entry['source']
            if source.resolve() != source:
                raise ValueError('Aliased provisioning recovery source')
            value = existing(source)
            if not value:
                raise ValueError('Missing provisioning recovery source')
            destination = tree / entry['path']
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('xb') as stream:
                os.fchmod(stream.fileno(), entry['mode'])
                stream.write(value)
        return install(tree, {entry['path']: entry['mode'] for entry in selected},
                       state=Path(host_root) / 'var/lib/mindflayer-elderbrain', host_root=host_root)


if __name__ == '__main__':
    if os.geteuid() != 0:
        raise SystemExit('Recovery provisioning requires root')
    result = provision()
    print(json.dumps({key: result[key] for key in ('state', 'bundle', 'activationReady')}))
