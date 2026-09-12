"""One isolated browser per connected output, reconciled across hotplug events."""
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import time
import tempfile
import fcntl
from urllib.parse import urlsplit

SETUP = 'https://127.0.0.1/elderbrain/'
CONFIG = Path('/run/elderbrain-browser/config.json')
BEAMER = Path('/run/elderbrain-browser/beamer.json')
STATES = {'ready', 'unavailable', 'world-not-running', 'module-unavailable', 'pairing-required',
          'review-required', 'unsupported-version', 'origin-mismatch', 'login-failed', 'canvas-unavailable', 'stopped'}


def drain_status(child, previous, revision):
    """Only fixed state labels cross from the worker; discard all other output."""
    buffer = getattr(child, 'status_buffer', b'')
    for _ in range(8):
        try:
            chunk = os.read(child.stdout.fileno(), 1024)
        except BlockingIOError:
            break
        if not chunk:
            break
        buffer += chunk
        if len(buffer) > 4096:
            buffer = b''
            previous = {'state': 'unavailable', 'revision': revision, 'observedAt': time.time()}
            break
        while b'\n' in buffer:
            line, buffer = buffer.split(b'\n', 1)
            try:
                value = json.loads(line)
                state = value.get('state') if isinstance(value, dict) else None
                if state in STATES:
                    previous = {'state': state, 'revision': revision, 'observedAt': time.time()}
            except (ValueError, TypeError):
                pass
    child.status_buffer = buffer
    return previous


def write_status(file, views):
    descriptor, temporary = tempfile.mkstemp(prefix='.beamer-status-', dir=file.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump({'updatedAt': time.time(), 'views': views}, stream)
        os.replace(temporary, file)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_beamer():
    from beamer_runtime import read_private
    try:
        return read_private(BEAMER, owners=(0,), mask=0o027)
    except (ValueError, OSError):
        return None


def worker_packet(browser, view, credential):
    if view['mode'] != 'player' or view['index'] not in (0, 1):
        raise ValueError('Invalid Beamer view')
    return {'browser': browser, 'index': view['index'],
            'profile': f'/var/lib/mindflayer-elderbrain/browser/profile-{view["index"]}-player',
            'origin': 'http://127.0.0.1:30000', 'credential': credential}


def safe_url(value):
    if not isinstance(value, str) or len(value) > 2048 or re.search(r'[\x00-\x20\x7f]', value):
        raise ValueError('Invalid browser URL')
    url = urlsplit(value)
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
        raise ValueError('Invalid browser URL')
    return value


def plan(config, outputs, token):
    connected = sorted({item['name'] for item in outputs if item.get('active') and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', item.get('name', ''))})
    # Completion is an onboarding indicator, not an override of saved displays.
    views = config.get('views')
    if views is None or views == [] and not config.get('configured'):
        views = [{'mode': 'admin', 'url': 'http://foundry.elderbrain.local', 'output': ''}]
    if not isinstance(views, list) or not 1 <= len(views) <= 2:
        raise ValueError('Invalid browser views')
    # Explicit assignments take priority over automatic selection.
    reserved = {view.get('output') for view in views if view.get('output')}
    used = set()
    result = []
    for index, view in enumerate(views):
        output = view.get('output') or next((name for name in connected if name not in used and name not in reserved), None)
        if output not in connected or output in used:
            continue
        mode = view.get('mode', 'player')
        if mode not in ('admin', 'player'):
            raise ValueError('Invalid browser mode')
        target = safe_url(view.get('url'))
        extras = view.get('tabs', [])
        if not isinstance(extras, list) or len(extras) > 10:
            raise ValueError('Invalid browser tabs')
        extras = [safe_url(value) for value in extras]
        setup = SETUP + '#kiosk-keyboard=' + token
        urls = [setup, target, *extras] if mode == 'admin' else [setup if target == SETUP else target]
        result.append({'index': index, 'output': output, 'mode': mode, 'urls': urls})
        used.add(output)
    return result


def browser_args(browser, view):
    return [browser, f'--class=elderbrain-view-{view["index"]}', '--ozone-platform=wayland',
            '--enable-features=UseOzonePlatform', '--no-first-run', '--no-default-browser-check',
            '--hide-crash-restore-bubble',
            f'--user-data-dir=/var/lib/mindflayer-elderbrain/browser/profile-{view["index"]}-{view["mode"]}',
            *(['--kiosk'] if view['mode'] == 'player' else ['--new-window']), *view['urls']]


def main():
    # A replaced Sway session may still have a launcher finishing its cleanup.
    # Hold one lock for the complete lifetime, including cleanup, before reusing units.
    lock_path = Path(os.environ['XDG_RUNTIME_DIR']) / 'browser-launcher.lock'
    launcher_lock = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    fcntl.flock(launcher_lock, fcntl.LOCK_EX)
    from browser_process import launch, terminate, stop_view
    for index in (0, 1):
        stop_view(index)
    browser = next((path for name in ('google-chrome-stable', 'chromium', 'chromium-browser') if (path := shutil.which(name))), None)
    if not browser:
        raise RuntimeError('Chromium-family browser is not installed')
    try:
        config = json.loads(CONFIG.read_text())
    except FileNotFoundError:
        config = {'configured': False}
    token = secrets.token_hex(32)
    descriptor = os.open(Path(os.environ['XDG_RUNTIME_DIR']) / 'keyboard-token', os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(token)
    children = {}
    rules = {}
    retry_after = {}
    statuses = {}
    status_file = Path(os.environ['XDG_RUNTIME_DIR']) / 'beamer-status.json'
    running = True

    def stop(_signal, _frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while running:
            response = subprocess.run(['swaymsg', '-r', '-t', 'get_outputs'], capture_output=True, text=True, check=True, timeout=5)
            desired = {view['index']: view for view in plan(config, json.loads(response.stdout), token)}
            credential = read_beamer()
            for view in desired.values():
                if view['mode'] == 'player':
                    view['beamerRevision'] = credential['revision'] if credential else None
            for index, (view, child) in list(children.items()):
                if view['mode'] == 'player':
                    statuses[index] = drain_status(child, statuses.get(index), view['beamerRevision'])
                if desired.get(index) != view or child.poll() is not None:
                    if desired.get(index) == view and view['mode'] == 'player':
                        retry_after[index] = (view.get('beamerRevision'), time.monotonic() + 60)
                    terminate(child)
                    if view['mode'] == 'player':
                        if statuses.get(index, {}).get('state') == 'ready':
                            statuses[index] = {'state': 'unavailable', 'revision': view['beamerRevision'], 'observedAt': time.time()}
                        child.stdout.close()
                    del children[index]
            for index, view in desired.items():
                if index in children:
                    continue
                if view['mode'] == 'player':
                    # Do not reopen an old authenticated profile when pairing is removed.
                    if credential is None:
                        continue
                    revision, deadline = retry_after.get(index, (None, 0))
                    if revision == view['beamerRevision'] and time.monotonic() < deadline:
                        continue
                rule = (index, view['output'], view['mode'])
                if rules.get(index) != rule:
                    criteria = f'[app_id="elderbrain-view-{index}"]'
                    commands = f'for_window {criteria} move container to output "{view["output"]}"; for_window {criteria} fullscreen {"enable" if view["mode"] == "player" else "disable"}'
                    result = subprocess.run(['swaymsg', '-r', commands], capture_output=True, text=True, check=True, timeout=5)
                    if not all(item.get('success') for item in json.loads(result.stdout)):
                        raise RuntimeError('Unable to assign browser output')
                    rules[index] = rule
                if view['mode'] == 'player':
                    child = launch(index, ['/usr/bin/node', '/opt/mindflayer-elderbrain/beamer/beamer-worker.mjs'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
                    os.set_blocking(child.stdout.fileno(), False)
                    statuses[index] = {'state': 'pending-verification', 'revision': view['beamerRevision'], 'observedAt': time.time()}
                    try:
                        child.stdin.write(json.dumps(worker_packet(browser, view, credential)).encode())
                        child.stdin.close()
                    except (BrokenPipeError, OSError):
                        terminate(child)
                        child.stdout.close()
                        retry_after[index] = (view['beamerRevision'], time.monotonic() + 60)
                        continue
                else:
                    child = launch(index, browser_args(browser, view))
                children[index] = view, child
            report = []
            for index, view in desired.items():
                if view['mode'] == 'player':
                    entry = statuses.get(index) or {}
                    if not credential or entry.get('revision') != credential['revision']:
                        entry = {'state': 'pairing-required' if not credential else 'pending-verification',
                                 'revision': credential['revision'] if credential else None, 'observedAt': time.time()}
                    report.append({'index': index, **entry})
            write_status(status_file, report)
            time.sleep(2)
    finally:
        for _view, child in children.values():
            terminate(child)
        status_file.unlink(missing_ok=True)
        os.close(launcher_lock)


if __name__ == '__main__':
    main()
