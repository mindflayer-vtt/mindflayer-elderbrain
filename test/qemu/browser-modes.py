import json
import os
from pathlib import Path
import pwd
import subprocess
import time

if os.geteuid() != 0 or subprocess.run(['systemd-detect-virt', '--vm'], capture_output=True, text=True).stdout.strip() not in ('kvm', 'qemu'):
    raise SystemExit('Run only as root in the disposable QEMU appliance VM')

uid = pwd.getpwnam('elderbrain-kiosk').pw_uid
config = Path('/var/lib/mindflayer-elderbrain/elderbrain/config.json')
original = config.read_bytes() if config.exists() else None
original_stat = config.stat() if config.exists() else None

def sway(*args):
    sockets = list(Path(f'/run/user/{uid}').glob('sway-ipc.*.sock'))
    assert len(sockets) == 1, 'Expected one Sway session'
    return json.loads(subprocess.run(['runuser', '-u', 'elderbrain-kiosk', '--', 'swaymsg', '-s', str(sockets[0]), '-r', *args], capture_output=True, text=True, check=True, timeout=5).stdout)

def windows(node, output=None):
    if node.get('type') == 'output':
        output = node.get('name')
    result = [(node, output)] if str(node.get('app_id', '')).startswith('elderbrain-view-') else []
    for child in node.get('nodes', []) + node.get('floating_nodes', []):
        result += windows(child, output)
    return result

def wait_windows(count, fullscreen):
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        try:
            result = windows(sway('-t', 'get_tree'))
            if len(result) == count and all((item['fullscreen_mode'] != 0) == fullscreen for item, _ in result):
                return result
        except Exception:
            pass
        time.sleep(1)
    print('Observed windows:', [(node.get('app_id'), node.get('fullscreen_mode'), output) for node, output in result], flush=True)
    raise AssertionError('Browser count or fullscreen mode did not match')

def configure(views):
    config.write_text(json.dumps({'version': 1, 'configured': True, 'domain': 'elderbrain.local', 'controllers': {}, 'views': views}))
    config.chmod(0o600)
    os.chown(config, 1000, 1000)
    subprocess.run(['systemctl', 'restart', 'elderbrain-graphics'], check=True, timeout=45)

try:
    active = [item['name'] for item in sway('-t', 'get_outputs') if item['active']]
    assert len(active) == 1, 'This test expects the VM single-monitor baseline'
    url = 'https://127.0.0.1/elderbrain/'
    configure([{'output': '', 'url': url, 'mode': 'admin', 'tabs': ['https://127.0.0.1/elderbrain/network']},
               {'output': '', 'url': url, 'mode': 'player', 'tabs': []}])
    admin = wait_windows(1, False)
    assert admin[0][1] == active[0]
    projected = Path('/run/elderbrain-browser/config.json').stat()
    assert projected.st_uid == 0 and projected.st_mode & 0o777 == 0o640
    assert subprocess.run(['runuser', '-u', 'elderbrain-kiosk', '--', 'test', '-r', str(config)]).returncode != 0
    assert subprocess.run(['runuser', '-u', 'elderbrain-kiosk', '--', 'test', '-r', '/run/elderbrain-browser/config.json']).returncode == 0
    argv = Path(f'/proc/{admin[0][0]["pid"]}/cmdline').read_bytes().split(b'\0')
    assert b'--kiosk' not in argv
    urls = [item.decode() for item in argv if item.startswith(b'https://')]
    assert len(urls) == 3 and urls[0].startswith(url + '#kiosk-keyboard=') and urls[1] == url and urls[2].endswith('/network')
    print('PASS: single-monitor administration browser, no overlapping second window, tab ordering and output placement.', flush=True)
    configure([{'output': '', 'url': url, 'mode': 'admin', 'tabs': []},
               {'output': '', 'url': url, 'mode': 'admin', 'tabs': []}])
    wait_windows(1, False)
    created = sway('create_output')
    assert all(item.get('success') for item in created), 'Virtual output creation unsupported'
    two = wait_windows(2, False)
    assert len({output for _, output in two}) == 2
    virtual = next(output for _, output in two if output not in active)
    assert all(item.get('success') for item in sway(f'output "{virtual}" disable'))
    remaining = wait_windows(1, False)
    assert remaining[0][1] == active[0]
    print('PASS: two distinct outputs and unplug reconciliation without overlapping windows.', flush=True)
    configure([{'output': active[0], 'url': url, 'mode': 'player', 'tabs': []}])
    player = wait_windows(1, True)
    argv = Path(f'/proc/{player[0][0]["pid"]}/cmdline').read_bytes().split(b'\0')
    assert b'--kiosk' in argv
    assert any(b'profile-0-player' in item for item in argv)
    print('PASS: player kiosk fullscreen and separate profile.', flush=True)
    configure([{'output': 'disconnected-test-monitor', 'url': url, 'mode': 'player', 'tabs': []}])
    wait_windows(0, False)
    time.sleep(3)
    assert not windows(sway('-t', 'get_tree'))
    print('PASS: disconnected selected output does not launch an overlapping browser.', flush=True)
finally:
    if original is None:
        config.unlink(missing_ok=True)
    else:
        config.write_bytes(original)
        config.chmod(original_stat.st_mode & 0o777)
        os.chown(config, original_stat.st_uid, original_stat.st_gid)
    subprocess.run(['systemctl', 'restart', 'elderbrain-graphics'], check=True, timeout=45)
    print('Original VM configuration restored; new launcher retained.', flush=True)
