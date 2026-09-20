"""One isolated browser per connected output, reconciled across hotplug events."""
import hashlib
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
PLAYER_MESSAGES = {
    'pairing-required': ('Player display setup required',
                         'Ask an administrator to configure the Beamer credentials in Elderbrain Setup under Displays.'),
    'world-not-running': ('No Foundry world is running',
                          'Ask an administrator to launch the configured Foundry world. This display will connect automatically.'),
    'module-unavailable': ('Mindflayer module unavailable',
                           'Ask an administrator to enable the Mindflayer module in the configured Foundry world.'),
    'review-required': ('Beamer configuration needs review',
                        'Ask an administrator to review the Beamer user and permissions in Elderbrain Setup.'),
    'unsupported-version': ('Mindflayer module update required',
                            'Ask an administrator to install a compatible Mindflayer module version.'),
    'origin-mismatch': ('Foundry address mismatch',
                        'Ask an administrator to review the Foundry address and Beamer configuration.'),
    'login-failed': ('Beamer login failed',
                     'Ask an administrator to verify the Beamer username and password.'),
    'canvas-unavailable': ('No player scene is available',
                           'Ask the game master to activate a scene for players.'),
    'unavailable': ('Player display unavailable',
                    'Ask an administrator to check Foundry. This display will retry automatically.'),
}
PLAYER_PAGE = '''<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: dark; font-family: system-ui, sans-serif; }}
  body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: #090b13; color: #f8fafc; }}
  main {{ max-width: 44rem; padding: 3rem; text-align: center; }}
  h1 {{ margin: 0 0 1rem; font-size: clamp(2rem, 5vw, 4rem); }}
  p {{ margin: 0; color: #cbd5e1; font-size: clamp(1.1rem, 2.5vw, 1.75rem); line-height: 1.5; }}
</style>
<main>
  <h1>{title}</h1>
  <p>{message}</p>
</main>
</html>
'''


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


def outputs_suspended(outputs, children):
    """Keep existing views while Sway temporarily releases DRM for another VT."""
    return isinstance(outputs, list) and not outputs and bool(children)


def connector_family(name):
    return re.sub(r'\d+$', '', name)


def monitor_id(output):
    identity = '\0'.join(str(output.get(key) or '').strip()[:128]
                         for key in ('make', 'model', 'serial'))
    if not identity.replace('\0', ''):
        return ''
    return 'monitor-' + hashlib.sha256(identity.encode()).hexdigest()


def renumbered_outputs(views, connected):
    """Map a completely renumbered connector set while preserving display order."""
    configured = [view.get('output') for view in views]
    if (len(configured) != len(connected) or not all(configured)
            or set(configured) & set(connected)):
        return {}
    previous = sorted(configured)
    current = sorted(connected)
    if ([connector_family(name) for name in previous]
            != [connector_family(name) for name in current]):
        return {}
    return dict(zip(previous, current))


def assigned_outputs(views, connected, identities):
    """Resolve configured outputs, keeping administration visible during hotplug."""
    renumbered = renumbered_outputs(views, connected)
    requested = [renumbered.get(view.get('output'), view.get('output')) for view in views]
    assigned = {}
    for index, output in enumerate(requested):
        identity_output = identities.get(views[index].get('displayId'))
        if identity_output and identity_output not in assigned.values():
            assigned[index] = identity_output
        elif output in connected and output not in assigned.values():
            assigned[index] = output

    admin = next((index for index, view in enumerate(views)
                  if view.get('mode', 'player') == 'admin'), None)
    if admin is not None and admin not in assigned and connected:
        free = [name for name in connected if name not in assigned.values()]
        if free:
            expected = requested[admin]
            matching = [name for name in free
                        if expected and connector_family(name) == connector_family(expected)]
            assigned[admin] = (matching or free)[0]
        elif len(connected) == 1:
            assigned = {admin: connected[0]}

    for index, output in enumerate(requested):
        if index in assigned:
            continue
        free = [name for name in connected if name not in assigned.values()]
        if not free:
            continue
        if output:
            free = [name for name in free
                    if connector_family(name) == connector_family(output)]
        if free:
            assigned[index] = free[0]
    return assigned


def plan(config, outputs, token):
    active = [item for item in outputs
              if item.get('active') and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', item.get('name', ''))]
    connected = sorted({item['name'] for item in active})
    observed = [monitor_id(item) for item in active]
    identities = {identity: item['name'] for item, identity in zip(active, observed)
                  if identity and observed.count(identity) == 1}
    # Completion is an onboarding indicator, not an override of saved displays.
    views = config.get('views')
    if views is None or views == [] and not config.get('configured'):
        views = [{'mode': 'admin', 'url': 'https://foundry.elderbrain.local', 'output': ''}]
    if not isinstance(views, list) or not 1 <= len(views) <= 2:
        raise ValueError('Invalid browser views')
    assigned = assigned_outputs(views, connected, identities)
    used = set()
    result = []
    for index, view in enumerate(views):
        output = assigned.get(index)
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


def player_status_page(directory, index, state):
    if index not in (0, 1) or state not in PLAYER_MESSAGES:
        raise ValueError('Invalid player display state')
    title, message = PLAYER_MESSAGES[state]
    path = directory / f'beamer-status-{index}.html'
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(PLAYER_PAGE.format(title=title, message=message))
    return path.as_uri()


def player_status_args(browser, view, runtime, state):
    placeholder = {**view, 'urls': [player_status_page(runtime, view['index'], state)]}
    args = browser_args(browser, placeholder)
    profile = f'--user-data-dir={runtime}/profile-{view["index"]}-status'
    args[next(index for index, value in enumerate(args) if value.startswith('--user-data-dir='))] = profile
    return args


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
    runtime = Path(os.environ['XDG_RUNTIME_DIR'])
    running = True

    def stop(_signal, _frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while running:
            response = subprocess.run(['swaymsg', '-r', '-t', 'get_outputs'], capture_output=True, text=True, check=True, timeout=5)
            outputs = json.loads(response.stdout)
            # Sway reports no outputs while another virtual terminal owns the
            # display. Stopping Chrome here destroys the first-login form and
            # tabs merely because the user viewed the bootstrap password.
            if outputs_suspended(outputs, children):
                time.sleep(2)
                continue
            desired = {view['index']: view for view in plan(config, outputs, token)}
            credential = read_beamer()
            for index, view in desired.items():
                if view['mode'] == 'player':
                    view['beamerRevision'] = credential['revision'] if credential else None
                    if credential is None:
                        view['placeholderState'] = 'pairing-required'
                    else:
                        revision, deadline = retry_after.get(index, (None, 0))
                        if revision == view['beamerRevision'] and time.monotonic() < deadline:
                            state = statuses.get(index, {}).get('state', 'unavailable')
                            view['placeholderState'] = state if state in PLAYER_MESSAGES else 'unavailable'
            for index, (view, child) in list(children.items()):
                if view['mode'] == 'player' and child.stdout is not None:
                    statuses[index] = drain_status(child, statuses.get(index), view['beamerRevision'])
                if desired.get(index) != view or child.poll() is not None:
                    if desired.get(index) == view and view['mode'] == 'player':
                        retry_after[index] = (view.get('beamerRevision'), time.monotonic() + 60)
                    terminate(child)
                    if view['mode'] == 'player' and child.stdout is not None:
                        if statuses.get(index, {}).get('state') == 'ready':
                            statuses[index] = {'state': 'unavailable', 'revision': view['beamerRevision'], 'observedAt': time.time()}
                        child.stdout.close()
                    del children[index]
            for index, view in desired.items():
                if index in children:
                    continue
                if (view['mode'] == 'player' and credential is not None
                        and 'placeholderState' not in view):
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
                if view.get('placeholderState'):
                    state = view['placeholderState']
                    child = launch(index, player_status_args(browser, view, runtime, state))
                    statuses[index] = {'state': state, 'revision': view['beamerRevision'],
                                       'observedAt': time.time()}
                elif view['mode'] == 'player' and credential is not None:
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
