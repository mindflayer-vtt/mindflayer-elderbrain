"""Prepare cached-image baseline without changing the disposable VM runtime."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'appliance/lib'))
from release_baseline import prepare

assert os.geteuid() == 0
assert Path('/sys/class/dmi/id/product_name').read_text().startswith('Standard PC')
assert subprocess.check_output(['lsblk', '-dn', '-o', 'SERIAL', '/dev/vda'], text=True).strip() == 'elderbrain-vm-test'
runtime = Path('/opt/mindflayer-elderbrain')
before = (runtime / 'compose.yaml').read_bytes()
directory = Path(tempfile.mkdtemp(prefix='elderbrain-offline-baseline-', dir='/root'))
result = prepare(runtime, state=Path('/var/lib/mindflayer-elderbrain'), directory=directory)
assert (runtime / 'compose.yaml').read_bytes() == before
assert result['activationReady'] is False
print(json.dumps({key: result[key] for key in ('state', 'directory', 'activationReady')}), flush=True)
