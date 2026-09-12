#!/usr/bin/python3
"""Test-only pause after real Netplan apply, before the worker can record success."""
import os
from pathlib import Path
import subprocess
import sys
import time

if sys.argv[1:] not in (['apply'], ['generate']):
    raise SystemExit(2)
result = subprocess.run(['/usr/sbin/netplan', *sys.argv[1:]])
if result.returncode:
    raise SystemExit(result.returncode)
if sys.argv[1:] == ['apply']:
    try:
        fd = os.open(Path(__file__).parent / 'paused', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        pass
    else:
        os.close(fd)
        time.sleep(60)  # Production run_netplan still enforces its own 30-second timeout.
