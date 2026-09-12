"""Inspect the actual detached update job and verify terminal VM health."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'appliance/lib'))
from host_jobs import JobStore
from release_recovery import health
from release_services import UpdateServices


def command(*args):
    return subprocess.check_output(args, text=True, timeout=60).strip()


assert os.geteuid() == 0
assert Path('/sys/class/dmi/id/product_name').read_text().startswith('Standard PC')
assert command('lsblk', '-dn', '-o', 'SERIAL', '/dev/vda') == 'elderbrain-vm-test'
evidence = json.loads(Path(sys.argv[1]).read_text())
state, runtime = Path('/var/lib/mindflayer-elderbrain'), Path('/opt/mindflayer-elderbrain')
record = JobStore(state / 'jobs').read(evidence['id'])
if record['state'] in ('queued', 'running'):
    scope = 'elderbrain-job-' + record['id'] + '.scope'
    assert command('systemctl', 'is-active', scope) == 'active'
    cgroup = command('systemctl', 'show', scope, '--property=ControlGroup', '--value')
    assert cgroup.endswith('/' + scope) and 'elderbrain-management.service' not in cgroup
    print(json.dumps({'id': record['id'], 'state': record['state'], 'stage': record.get('stage'),
                      'scope': scope}), flush=True)
else:
    assert record['state'] == 'completed', {'id': record['id'], 'state': record['state'], 'error': record.get('error')}
    assert record['result']['version'] == evidence['version']
    assert (runtime / 'VERSION').read_text() == evidence['version'] + '\n'
    assert command('systemctl', 'show', 'elderbrain-management', '--property=InvocationID', '--value') != evidence['managementBefore']
    maintenance = json.loads((state / 'maintenance/maintenance.json').read_text())
    assert maintenance['jobId'] == record['id'] and maintenance['id'] == record['result']['id']
    services = UpdateServices(runtime, health_check=lambda saved: health(saved, state))
    services.validate()
    health(services.snapshot(), state)
    print(json.dumps({'state': 'detached-update-job-passed', 'id': record['id'], 'version': evidence['version']}), flush=True)
