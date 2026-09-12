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
import time

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'appliance/lib'))
from provisioning.recovery_bootstrap import staged_payload
from release_bootstrap import commit_candidate, prepare_candidate
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
failures.add_argument('--download-job', type=Path, help='Reuse the explicitly identified prior disposable job signing fixture')
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
if args.download_job:
    previous = args.download_job.resolve()
    assert previous.parent == Path('/root') and previous.name.startswith('elderbrain-signed-activation-')
    assert (previous / 'job.json').is_file()
    private, public = previous / 'test-private.pem', previous / 'test-public.pem'
    assert public.read_bytes() == Path('/etc/elderbrain/release-public.pem').read_bytes(), 'Only reuse the prior disposable test pin'
    assert not Path('/etc/elderbrain/release-source.json').exists(), 'Do not replace a configured source'
else:
    subprocess.run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048',
                '-out', str(private)], check=True, capture_output=True)
    private.chmod(0o600)
    subprocess.run(['openssl', 'pkey', '-in', str(private), '-pubout', '-out', str(public)], check=True, capture_output=True)
metadata = {'format': 2, 'kind': 'mindflayer-elderbrain-release', 'version': args.version, 'recoveryApi': 1,
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
if args.job or args.download_job:
    if args.job:
        assert not Path('/etc/elderbrain/release-public.pem').exists(), 'Do not replace an existing release trust pin'
        assert not Path('/etc/elderbrain/release-inventory.json').exists(), 'Do not replace an existing release inventory'
    dependencies = Path('/usr/lib/elderbrain-dependencies')
    releases = Path('/var/lib/elderbrain-releases')
    releases.mkdir(mode=0o700, exist_ok=True)
    (releases / 'staging').mkdir(mode=0o700, exist_ok=True)
    prepared = releases / 'prepared'
dependencies.mkdir(mode=0o700, exist_ok=bool(args.job or args.download_job))
prepared.mkdir(mode=0o700, exist_ok=bool(args.job or args.download_job))
manifest, signature, key = (bundle / 'manifest.json').read_bytes(), (bundle / 'manifest.sig').read_bytes(), public.read_bytes()
if not args.download_job:
    prepare(bundle / 'elderbrain-host.tar.zst', manifest, signature, key, paths, directory=prepared,
        platform=metadata['platform'], configuration_schema=1, environment_file=runtime / 'appliance.env',
        allow_download=False, dependency_archive=bundle / 'elderbrain-dependencies.tar.zst', dependency_directory=dependencies)
    print('Signed runtime prepared from cached images and offline dependencies', flush=True)
else:
    assert not (prepared / args.version).exists() and not (dependencies / args.version).exists()
    # Trust a fresh test TLS CA in this disposable guest only. No insecure TLS
    # flags or environment overrides are passed to the isolated worker.
    command('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
            '-subj', '/CN=Elderbrain disposable release test', '-addext', 'subjectAltName=IP:127.0.0.1',
            '-addext', 'basicConstraints=critical,CA:TRUE', '-keyout', str(evidence / 'tls.key'), '-out', str(evidence / 'tls.crt'))
    (evidence / 'tls.key').chmod(0o600)
    ca = Path('/usr/local/share/ca-certificates') / (evidence.name + '.crt')
    with ca.open('xb') as stream:
        stream.write((evidence / 'tls.crt').read_bytes())
    command('update-ca-certificates')
    inventory_file = Path('/etc/elderbrain/release-inventory.json')
    (evidence / 'previous-inventory.json').write_bytes(inventory_file.read_bytes())
    inventory_file.write_text(json.dumps(paths))
    with Path('/etc/elderbrain/release-source.json').open('x') as stream:
        json.dump({'baseUrl': 'https://127.0.0.1:18443/'}, stream)
    command('systemd-run', '--unit=elderbrain-release-test', '--collect', '--property=Type=exec',
            '/usr/bin/python3', str(ROOT / 'test/qemu/https-release-server.py'), str(evidence))
    from release_catalog import check
    for attempt in range(20):
        try:
            checked = check()
            break
        except ConnectionRefusedError:
            if attempt == 19:
                raise
            time.sleep(0.1)
    assert checked['release']['manifestSha256'] == hashlib.sha256(manifest).hexdigest()
    assert checked['release']['compatible'] is True
    print('CA-verified HTTPS announcement checked; runtime not prepared', flush=True)
if args.job or args.download_job:
    # Disposable VM only: independent pin and reviewed inventory. No production
    # key is generated or overwritten by this fixture.
    for destination, value in (() if args.download_job else ((Path('/etc/elderbrain/release-public.pem'), key),
            (Path('/etc/elderbrain/release-inventory.json'), json.dumps(paths).encode()))):
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
    recovery = prepare_candidate(tree, paths, recovery_api=metadata['recoveryApi'],
                                 state=Path('/var/lib/mindflayer-elderbrain'))
    try:
        result = activate(prepared / args.version, key, paths, dependency_directory=dependencies, bootstrap_tree=tree,
                          platform=metadata['platform'], configuration_schema=1, parent=evidence,
                          active_recovery=recovery['active'], recovery_api=metadata['recoveryApi'])
        assert result['state'] == 'completed'
        commit_candidate(recovery['candidate'], state=Path('/var/lib/mindflayer-elderbrain'))
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
