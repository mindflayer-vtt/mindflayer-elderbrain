"""Root-only ownership regression using a fresh temporary fixture, not user data."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

if os.geteuid() != 0:
    raise SystemExit('Run in a disposable test VM as root')
source = Path(sys.argv[1]).read_text()
commands = ['chown -hR 1000:1000 "$STATE/foundry"', 'chmod u+rwx "$STATE/foundry"']
assert all(command in source for command in commands)
root = Path(tempfile.mkdtemp(prefix='elderbrain-foundry-permissions-', dir='/tmp'))
root.chmod(0o755)
data = root / 'foundry'
data.mkdir(mode=0o755)
fixture = data / 'existing-config'
fixture.write_text('fixture only')
fixture.chmod(0o600)
outside = root / 'outside-target'
outside.write_text('must remain root-owned')
(data / 'outside-link').symlink_to(outside)
check = ['setpriv', '--reuid=1000', '--regid=1000', '--clear-groups',
         'sh', '-c', 'test -r "$1/existing-config" && test -w "$1" && test -x "$1"',
         'volume-check', str(data)]
assert subprocess.run(check).returncode != 0, 'Fixture must reproduce original permission failure'
subprocess.run(['bash', '-euc', '\n'.join(commands)], env={**os.environ, 'STATE': str(root)}, check=True)
subprocess.run(check, check=True)
subprocess.run(['setpriv', '--reuid=1000', '--regid=1000', '--clear-groups',
                'python3', '-c', 'import pathlib,sys; p=pathlib.Path(sys.argv[1])/"write-test"; p.write_text("ok"); assert p.read_text()=="ok"; p.unlink()',
                str(data)], check=True)
assert outside.stat().st_uid == 0, 'Ownership repair must not follow symlinks outside data'
assert fixture.read_text() == 'fixture only'
print(f'PASS: UID/GID 1000 read/write, existing file preservation, no symlink traversal; fixture {root}')
