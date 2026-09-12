#!/usr/bin/env python3
"""Qualify relocated browser modules as the actual kiosk user in disposable QEMU."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'appliance/lib'))
from release_runtime import browser_modules


def main():
    if (os.geteuid() != 0 or subprocess.check_output(
            ['lsblk', '-dn', '-o', 'SERIAL', '/dev/vda'], text=True).strip() != 'elderbrain-vm-test'):
        raise SystemExit('Requires disposable Elderbrain QEMU guest')
    prefix = Path(sys.argv[1]).resolve()
    before = prefix.stat().st_mode
    evidence = Path(tempfile.mkdtemp(prefix='elderbrain-browser-deployment-', dir='/tmp'))
    evidence.chmod(0o711)
    modules = evidence / 'node_modules'
    browser_modules(prefix / 'beamer/node_modules', modules)
    subprocess.run(['runuser', '-u', 'elderbrain-kiosk', '--', '/usr/bin/node', '-e',
                    'const p=require(process.argv[1]); if(!p.chromium)process.exit(1)',
                    str(modules / 'playwright-core')], check=True, cwd='/tmp')
    assert prefix.stat().st_mode == before and before & 0o777 == 0o700
    print('PASS: kiosk imports relocated browser modules; private prefix unchanged. Evidence: ' + str(evidence))


if __name__ == '__main__':
    main()
