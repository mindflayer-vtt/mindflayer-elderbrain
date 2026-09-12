"""Complete signed test-release activation on the identified disposable VM."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from contextlib import nullcontext
from unittest.mock import patch
import uuid
import hashlib

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'appliance/lib'))
from provisioning.recovery_bootstrap import provision, staged_payload
from release_apply import activate
from release_prepare import prepare
from release_recovery import health
from backup_service import save_record
from host_jobs import JobStore


def command(*args):
    return subprocess.check_output(args, text=True, timeout=60).strip()


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('dependency_inputs', type=Path)
parser.add_argument('--version', default='1.0.1')
failures = parser.add_mutually_exclusive_group()
failures.add_argument('--fail-health', action='store_true')
failures.add_argument('--interrupt', action='store_true')
failures.add_argument('--job', action='store_true')
args = parser.parse_args()
assert os.geteuid() == 0
assert Path('/sys/class/dmi/id/product_name').read_text().startswith('Standard PC')
assert command('lsblk', '-dn', '-o', 'SERIAL', '/dev/vda') == 'elderbrain-vm-test'
assert args.dependency_inputs.is_dir()
runtime = Path('/opt/mindflayer-elderbrain')
previous_version = (runtime / 'VERSION').read_text()
previous_compose = (runtime / 'compose.yaml').read_bytes()
current = yaml.safe_load((runtime / 'compose.yaml').read_bytes())
references = {}
for name, reference in {**{name: current['services'][name]['image'] for name in
                         ('traefik', 'mindflayer-server', 'foundry')},
                        'elderbrain-setup': 'elderbrain-setup-release-test:1.0.1'}.items():
    image = json.loads(command('docker', 'image', 'inspect', reference))[0]
    assert image['RepoDigests'], 'Signed test requires a real cached digest'
    references[name] = image['RepoDigests'][0]
evidence = Path(tempfile.mkdtemp(prefix='elderbrain-signed-activation-', dir='/root'))
print('Evidence: ' + str(evidence), flush=True)
spec = importlib.util.spec_from_file_location('assembler', ROOT / 'release/assemble.py')
assembler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assembler)
private, public = evidence / 'test-private.pem', evidence / 'test-public.pem'
subprocess.run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048',
                '-out', str(private)], check=True, capture_output=True)
private.chmod(0o600)
subprocess.run(['openssl', 'pkey', '-in', str(private), '-pubout', '-out', str(public)], check=True, capture_output=True)
metadata = {'format': 2, 'kind': 'mindflayer-elderbrain-release', 'version': args.version,
    'platform': {'os': 'ubuntu', 'release': '26.04', 'architecture': 'amd64'},
    'host': {'version': args.version, 'apiVersion': 1},
    'setup': {'version': '1.0.1', 'image': references.pop('elderbrain-setup'), 'hostApi': {'min': 1, 'max': 1}},
    'images': references, 'configurationSchema': 1, 'notes': 'Disposable VM signed activation only', 'downtimeSeconds': 120}
bundle = evidence / 'bundle'
assembler.assemble(metadata, ROOT, ROOT / 'release/host-files.json', bundle, private, public,
                   dependency_directory=args.dependency_inputs)
paths = {entry['path']: entry['mode'] for entry in assembler.host.entries(ROOT / 'release/host-files.json')}
paths['runtime/VERSION'] = 0o644
dependencies, prepared = evidence / 'dependencies', evidence / 'prepared'
if args.job:
    assert not Path('/etc/elderbrain/release-public.pem').exists(), 'Do not replace an existing release trust pin'
    assert not Path('/etc/elderbrain/release-inventory.json').exists(), 'Do not replace an existing release inventory'
    dependencies = Path('/usr/lib/elderbrain-dependencies')
    releases = Path('/var/lib/elderbrain-releases')
    releases.mkdir(mode=0o700, exist_ok=True)
    (releases / 'staging').mkdir(mode=0o700, exist_ok=True)
    prepared = releases / 'prepared'
dependencies.mkdir(mode=0o700, exist_ok=args.job)
prepared.mkdir(mode=0o700, exist_ok=args.job)
manifest, signature, key = (bundle / 'manifest.json').read_bytes(), (bundle / 'manifest.sig').read_bytes(), public.read_bytes()
prepare(bundle / 'elderbrain-host.tar.zst', manifest, signature, key, paths, directory=prepared,
    platform=metadata['platform'], configuration_schema=1, environment_file=runtime / 'appliance.env',
    allow_download=False, dependency_archive=bundle / 'elderbrain-dependencies.tar.zst', dependency_directory=dependencies)
print('Signed runtime prepared from cached images and offline dependencies', flush=True)
provision()
command('systemctl', 'daemon-reload')
if args.job:
    # Disposable VM only: independent pin and reviewed inventory. No production
    # key is generated or overwritten by this fixture.
    for destination, value in ((Path('/etc/elderbrain/release-public.pem'), key),
            (Path('/etc/elderbrain/release-inventory.json'), json.dumps(paths).encode())):
        with destination.open('xb') as stream:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    before = command('systemctl', 'show', 'elderbrain-management', '--property=InvocationID', '--value')
    submitted = JobStore('/var/lib/mindflayer-elderbrain/jobs').submit('update', {
        'version': args.version, 'manifestSha256': hashlib.sha256(manifest).hexdigest(),
        'confirmUpdate': True, 'confirmDowntime': True})
    save_record(evidence / 'job.json', {'id': submitted['id'], 'version': args.version, 'managementBefore': before})
    print(json.dumps({'state': 'update-job-submitted', 'id': submitted['id'],
                      'evidence': str(evidence / 'job.json')}), flush=True)
    raise SystemExit(0)  # Worker must survive this submitting process exiting.
marker = Path('/var/lib/mindflayer-elderbrain/foundry') / ('.elderbrain-rollback-test-' + uuid.uuid4().hex)
injected = []
if args.fail_health or args.interrupt:
    assert args.version + '\n' != previous_version
    with marker.open('xb') as stream:
        stream.write(b'before-update\n')
        stream.flush()
        os.fsync(stream.fileno())
def fail_health(saved, state, **options):
    health(saved, state, **options)
    if not injected:
        assert (runtime / 'VERSION').read_text() == args.version + '\n'
        with marker.open('wb') as stream:
            stream.write(b'changed-by-new-release\n')
            stream.flush()
            os.fsync(stream.fileno())
        injected.append(True)
        if args.interrupt:
            raise SystemExit('Injected post-start process loss')
        raise RuntimeError('Injected post-start update health failure')
with staged_payload() as (tree, _), \
        (patch('release_apply.health', side_effect=fail_health) if args.fail_health or args.interrupt else nullcontext()):
    try:
        result = activate(prepared / args.version, key, paths, dependency_directory=dependencies, bootstrap_tree=tree,
                          platform=metadata['platform'], configuration_schema=1, parent=evidence)
    except SystemExit as error:
        assert args.interrupt and str(error) == 'Injected post-start process loss'
        assert injected and marker.read_bytes() == b'changed-by-new-release\n'
        record = json.loads(Path('/var/lib/mindflayer-elderbrain/maintenance/maintenance.json').read_text())
        assert record['state'] == 'verifying-update' and record['dataMayHaveChanged'] is True
        saved = {'id': record['id'], 'marker': str(marker), 'version': previous_version,
                 'composeSha256': hashlib.sha256(previous_compose).hexdigest(),
                 'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
        save_record(evidence / 'interruption.json', saved)
        print(json.dumps({'state': 'signed-update-interrupted', 'id': record['id'],
                          'evidence': str(evidence / 'interruption.json')}), flush=True)
    except RuntimeError as error:
        assert args.fail_health and str(error) == 'Injected post-start update health failure'
        assert injected and marker.read_bytes() == b'before-update\n'
        assert (runtime / 'VERSION').read_text() == previous_version
        assert (runtime / 'compose.yaml').read_bytes() == previous_compose
        record = json.loads(Path('/var/lib/mindflayer-elderbrain/maintenance/maintenance.json').read_text())
        assert record['state'] == 'rolled-back' and record['dataRolledBack'] is True
        print(json.dumps({'state': 'signed-update-code-and-data-rollback-passed', 'id': record['id'],
                          'marker': str(marker), 'evidence': str(evidence)}), flush=True)
    else:
        assert not args.fail_health and not args.interrupt
        assert result['state'] == 'completed' and result['version'] == args.version
        assert (runtime / 'VERSION').read_text() == args.version + '\n'
        print(json.dumps(result), flush=True)
