#!/usr/bin/env python3
"""Create a ready disposable-VM administrator without exposing its password."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import tempfile


assert os.geteuid() == 0
assert Path('/sys/class/dmi/id/product_name').read_text().startswith('Standard PC')
assert subprocess.check_output(['lsblk', '-dn', '-o', 'SERIAL', '/dev/vda'], text=True).strip() == 'elderbrain-vm-test'
root = Path('/var/lib/mindflayer-elderbrain/elderbrain/secrets')
admin, initial = root / 'admin.json', root / 'initial-password'
info = admin.lstat()
assert stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
current = json.loads(admin.read_text())
assert current.get('schema') == 1 and current.get('mustChange') is True and current.get('verified') is False
bootstrap = initial.read_text().strip().split('-')
assert len(bootstrap) in (4, 8) and all(3 <= len(word) <= 8 and word.islower()
                                         and word.isalpha() for word in bootstrap)

password = secrets.token_urlsafe(24)
salt = secrets.token_hex(16)
hashed = hashlib.scrypt(password.encode(), salt=salt.encode(), n=32768, r=8, p=1,
                        dklen=32, maxmem=64 * 1024 * 1024).hex()
account = {
    'schema': 1, 'password': salt + ':' + hashed, 'mustChange': False,
    'email': 'vm-update@example.invalid', 'verified': True,
    'smtp': {'host': 'smtp.example.invalid', 'port': 587, 'secure': False,
             'user': '', 'password': '', 'from': 'vm-update@example.invalid'},
    'recoveryHash': hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
}
temporary = root / ('.admin-vm-' + secrets.token_hex(8))
descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
with os.fdopen(descriptor, 'w') as stream:
    os.fchown(stream.fileno(), info.st_uid, info.st_gid)
    json.dump(account, stream, separators=(',', ':'))
    stream.flush()
    os.fsync(stream.fileno())
os.replace(temporary, admin)
initial.unlink()
directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(directory)
finally:
    os.close(directory)

evidence = Path(tempfile.mkdtemp(prefix='elderbrain-live-admin-', dir='/root'))
credential = evidence / 'password'
with credential.open('x') as stream:
    os.fchmod(stream.fileno(), 0o600)
    stream.write(password + '\n')
    stream.flush()
    os.fsync(stream.fileno())
print(evidence)
