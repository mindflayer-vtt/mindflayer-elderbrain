"""Disposable VM: exercise the per-view service with actual sandboxed Chrome/Sway."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

spec = importlib.util.spec_from_file_location('browser_process', '/tmp/elderbrain-browser-process.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
runtime = Path(f'/run/user/{os.getuid()}')
sockets = list(runtime.glob('sway-ipc.*.sock'))
assert len(sockets) == 1, 'Expected exactly one disposable compositor'
os.environ.update(XDG_RUNTIME_DIR=str(runtime), WAYLAND_DISPLAY='wayland-1', SWAYSOCK=str(sockets[0]))


def windows():
    tree = json.loads(subprocess.check_output(['swaymsg', '-r', '-t', 'get_tree'], env=os.environ))
    found = []
    def walk(node):
        if node.get('app_id') == 'elderbrain-view-proof':
            found.append(node)
        for child in node.get('nodes', []) + node.get('floating_nodes', []):
            walk(child)
    walk(tree)
    return found


assert not windows(), 'Existing test view must not be overwritten'
with tempfile.TemporaryDirectory(prefix='elderbrain-wayland-profile-') as profile:
    child = helper.launch(1, ['/usr/bin/google-chrome-stable', '--class=elderbrain-view-proof',
                             '--ozone-platform=wayland', '--no-first-run', '--no-default-browser-check',
                             f'--user-data-dir={profile}', '--new-window', 'about:blank', 'about:version'])
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if len(windows()) == 1:
                break
            assert child.poll() is None, 'Browser service exited before displaying its window'
            time.sleep(0.2)
        else:
            raise AssertionError('No Wayland browser window appeared')
        print('PASS: actual Chrome window appeared in Sway through a per-view user service.')
    finally:
        helper.terminate(child)
    assert not windows(), 'Stopped browser window remains in the compositor'
    print('PASS: stopping the per-view service removed its actual Wayland window.')
