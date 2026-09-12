"""Disposable VM only: credentials enter via SSH stdin and never reach diagnostics."""
import importlib.util
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time

spec = importlib.util.spec_from_file_location('browser_process', '/tmp/elderbrain-browser-process.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
credential = json.loads(sys.stdin.read(4096))
assert credential['worldId'] == 'elderbrain-beamer', 'Not the disposable world'
runtime = Path(f'/run/user/{os.getuid()}')
sockets = list(runtime.glob('sway-ipc.*.sock'))
assert len(sockets) == 1
os.environ.update(XDG_RUNTIME_DIR=str(runtime), WAYLAND_DISPLAY='wayland-1', SWAYSOCK=str(sockets[0]))


def windows():
    tree = json.loads(subprocess.check_output(['swaymsg', '-r', '-t', 'get_tree']))
    def count(node):
        return int(node.get('app_id') == 'elderbrain-view-1') + sum(count(child) for child in node.get('nodes', []) + node.get('floating_nodes', []))
    return count(tree)


assert windows() == 0, 'Existing display must not be replaced by the test'
child = helper.launch(1, ['/usr/bin/node', '/opt/mindflayer-elderbrain/beamer/beamer-worker.mjs'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
try:
    packet = {'index': 1, 'browser': '/usr/bin/google-chrome-stable',
              'profile': '/var/lib/mindflayer-elderbrain/browser/profile-1-player',
              'origin': 'http://127.0.0.1:30000', 'credential': credential}
    child.stdin.write(json.dumps(packet).encode())
    child.stdin.close()
    deadline = time.monotonic() + 90
    ready = 0
    while time.monotonic() < deadline:
        readable, _, _ = select.select([child.stdout], [], [], 1)
        if readable:
            line = child.stdout.readline(1024)
            if not line:
                raise AssertionError('Installed worker exited before verification')
            value = json.loads(line)
            assert value.get('state') == 'ready', 'Installed worker did not report ready'
            ready += 1
            if ready >= 2:
                assert windows() == 1, 'Expected one actual player window'
                print('PASS: installed Node worker logged into VM Foundry and maintained a real Wayland player window.', flush=True)
                break
    else:
        raise AssertionError('Installed worker verification timed out')
finally:
    helper.terminate(child)
    child.stdout.close()
assert windows() == 0, 'Stopped player window remains'
print('PASS: installed player worker and Wayland window cleaned up.', flush=True)
