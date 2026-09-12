"""Remove only the completed disposable HTTPS fixture's source and TLS trust."""
import json
import os
from pathlib import Path
import subprocess
import sys

assert os.geteuid() == 0
evidence = Path(sys.argv[1]).resolve()
assert evidence.parent == Path('/root') and evidence.name.startswith('elderbrain-signed-activation-')
# This verifier checks VM identity, terminal success and actual service health.
subprocess.run([sys.executable, str(Path(__file__).with_name('update-job-status.py')),
                str(evidence / 'job.json')], check=True)
job = json.loads((evidence / 'job.json').read_text())
record = json.loads((Path('/var/lib/mindflayer-elderbrain/jobs') / (job['id'] + '.json')).read_text())
assert record['state'] == 'completed'
source = Path('/etc/elderbrain/release-source.json')
assert not source.is_symlink()
assert json.loads(source.read_text()) == {'baseUrl': 'https://127.0.0.1:18443/'}
certificate = Path('/usr/local/share/ca-certificates') / (evidence.name + '.crt')
assert not certificate.is_symlink()
assert certificate.read_bytes() == (evidence / 'tls.crt').read_bytes()
unit = subprocess.check_output(['systemctl', 'show', 'elderbrain-release-test', '--property=ExecStart', '--value'], text=True)
assert str(evidence) in unit and 'https-release-server.py' in unit
subprocess.run(['systemctl', 'stop', 'elderbrain-release-test'], check=True, timeout=30)
source.unlink()
certificate.unlink()
subprocess.run(['update-ca-certificates'], check=True, timeout=60, stdout=subprocess.DEVNULL)
print('Removed temporary release source and guest TLS trust; signed release/test evidence retained.')
