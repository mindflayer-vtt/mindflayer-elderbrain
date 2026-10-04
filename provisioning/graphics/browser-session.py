"""One isolated browser per connected output, reconciled across hotplug events."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import select
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
          'review-required', 'role-review-required', 'permission-review-required',
          'module-review-required', 'unsupported-version', 'origin-mismatch', 'login-failed',
          'canvas-unavailable', 'stopped'}
TERMINAL_STATES = {'pairing-required', 'review-required', 'role-review-required',
                   'permission-review-required', 'module-review-required', 'unsupported-version',
                   'origin-mismatch', 'login-failed'}
PLAYER_MESSAGES = {
    'pairing-required': ('Player display setup required',
                         'Ask an administrator to configure the Beamer credentials in Elderbrain Setup under Displays.'),
    'world-not-running': ('No Foundry world is running',
                          'Ask an administrator to launch the configured Foundry world. This display will connect automatically.'),
    'module-unavailable': ('Mindflayer module unavailable',
                           'Ask an administrator to enable the Mindflayer module in the configured Foundry world.'),
    'review-required': ('Beamer configuration needs review',
                        'Ask an administrator to review the Beamer user and permissions in Elderbrain Setup.'),
    'role-review-required': ('Beamer role needs review',
                             'Set the Foundry Beamer user role to Player or Trusted Player, then save its credentials again.'),
    'permission-review-required': ('Beamer permissions need review',
                                   'Remove all additional Foundry permissions from the Beamer user role.'),
    'module-review-required': ('Mindflayer Beamer setup needs review',
                               'Configure or adopt this user in the Mindflayer module Beamer user settings.'),
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


def next_retry(state, now):
    """Keep actionable configuration errors stable until credentials change."""
    return float('inf') if state in TERMINAL_STATES else now + 60


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
        resolution = view.get('resolution', '')
        match = re.fullmatch(r'(\d{2,5})x(\d{2,5})', resolution) if isinstance(resolution, str) else None
        if resolution and (not match or not 320 <= int(match.group(1)) <= 32768
                           or not 200 <= int(match.group(2)) <= 32768):
            raise ValueError('Invalid display resolution')
        target = safe_url(view.get('url'))
        extras = view.get('tabs', [])
        if not isinstance(extras, list) or len(extras) > 10:
            raise ValueError('Invalid browser tabs')
        extras = [safe_url(value) for value in extras]
        setup = SETUP + '#kiosk-keyboard=' + token
        urls = [setup, target, *extras] if mode == 'admin' else [setup if target == SETUP else target]
        result.append({'index': index, 'output': output, 'resolution': resolution,
                       'mode': mode, 'urls': urls})
        used.add(output)
    return result


def output_modes(output):
    raw = output.get('modes')
    if not isinstance(raw, list):
        return []
    modes = []
    for mode in raw[:256]:
        if not isinstance(mode, dict):
            continue
        width, height, refresh = (mode.get(key) for key in ('width', 'height', 'refresh'))
        if (type(width) is int and type(height) is int and type(refresh) is int
                and 320 <= width <= 32768 and 200 <= height <= 32768
                and 1000 <= refresh <= 1000000):
            value = (width, height, refresh)
            if value not in modes:
                modes.append(value)
    return modes


def preferred_mode(view, output):
    modes = output_modes(output)
    if not modes:
        return None
    requested = view.get('resolution', '')
    if requested:
        width, height = map(int, requested.split('x'))
        matching = [mode for mode in modes if mode[:2] == (width, height)]
        if matching:
            return max(matching, key=lambda mode: mode[2])
    return max(modes, key=lambda mode: (mode[0] * mode[1], mode[0], mode[1], mode[2]))


def apply_output_modes(desired, outputs):
    """Apply advertised modes only; unavailable saved choices fall back to highest."""
    changed = False
    by_name = {output.get('name'): output for output in outputs if output.get('active')}
    for view in desired.values():
        output = by_name.get(view.get('output'))
        selected = preferred_mode(view, output) if isinstance(output, dict) else None
        if selected is None:
            continue
        current = output.get('current_mode') or {}
        if tuple(current.get(key) for key in ('width', 'height', 'refresh')) == selected:
            continue
        width, height, refresh = selected
        command = (f'output "{view["output"]}" mode '
                   f'{width}x{height}@{refresh / 1000:.3f}Hz')
        try:
            response = subprocess.run(['swaymsg', '-r', command], capture_output=True,
                                      text=True, check=True, timeout=5)
            changed = all(item.get('success') for item in json.loads(response.stdout)) or changed
        except (OSError, subprocess.SubprocessError, ValueError, TypeError):
            continue
    return changed


def admin_cursor_target(desired, outputs):
    """Return the centre of the first connected administration display."""
    admin = next((desired[index] for index in sorted(desired)
                  if desired[index].get('mode') == 'admin'), None)
    if admin is None:
        return None
    output = next((item for item in outputs if item.get('active')
                   and item.get('name') == admin.get('output')), None)
    rect = output.get('rect') if isinstance(output, dict) else None
    if (not isinstance(rect, dict)
            or any(type(rect.get(key)) is not int for key in ('x', 'y', 'width', 'height'))
            or not 0 < rect['width'] <= 100000 or not 0 < rect['height'] <= 100000
            or not -1000000 <= rect['x'] <= 1000000 or not -1000000 <= rect['y'] <= 1000000):
        return None
    return admin['output'], rect['x'] + rect['width'] // 2, rect['y'] + rect['height'] // 2


def move_cursor(target):
    """Best-effort pointer placement must never take down the display session."""
    if target is None:
        return False
    output, x, y = target
    try:
        response = subprocess.run(
            ['swaymsg', '-r',
             f'focus output "{output}"; seat seat0 cursor set {x} {y}'], capture_output=True,
            text=True, check=True, timeout=5)
        return all(item.get('success') for item in json.loads(response.stdout))
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return False


def views_mapped(desired):
    """Wait to place the cursor until later-mapping windows cannot steal focus."""
    try:
        response = subprocess.run(
            ['swaymsg', '-r', '-t', 'get_tree'], capture_output=True, text=True,
            check=True, timeout=5)
        tree = json.loads(response.stdout)
        stack = [tree]
        app_ids = set()
        while stack:
            node = stack.pop()
            if not isinstance(node, dict):
                continue
            if isinstance(node.get('app_id'), str):
                app_ids.add(node['app_id'])
            for key in ('nodes', 'floating_nodes'):
                if isinstance(node.get(key), list):
                    stack.extend(node[key])
        return all(f'elderbrain-view-{index}' in app_ids for index in desired)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return False


def window_outputs():
    """Map managed browser indexes to their current Sway output."""
    try:
        response = subprocess.run(
            ['swaymsg', '-r', '-t', 'get_tree'], capture_output=True, text=True,
            check=True, timeout=5)
        result = {}
        stack = [(json.loads(response.stdout), None)]
        while stack:
            node, output = stack.pop()
            if not isinstance(node, dict):
                continue
            if node.get('type') == 'output' and node.get('name') != '__i3':
                output = node.get('name')
            app_id = node.get('app_id')
            match = re.fullmatch(r'elderbrain-view-([01])', app_id) if isinstance(app_id, str) else None
            if match and isinstance(output, str):
                result[int(match.group(1))] = output
            for key in ('nodes', 'floating_nodes'):
                if isinstance(node.get(key), list):
                    stack.extend((child, output) for child in node[key])
        return result
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return {}


def auxiliary_windows(tree, desired):
    """Find small Chrome toplevels without relying on site-controlled titles."""
    groups = {index: [] for index in desired}
    indexes_by_output = {view.get('output'): index for index, view in desired.items()
                         if isinstance(view.get('output'), str)}
    stack = [(tree, None)]
    while stack:
        node, output = stack.pop()
        if not isinstance(node, dict):
            continue
        if node.get('type') == 'output' and node.get('name') != '__i3':
            output = node.get('name')
        app_id = node.get('app_id')
        match = re.fullmatch(r'elderbrain-view-([01])', app_id) if isinstance(app_id, str) else None
        index = int(match.group(1)) if match else None
        # Chrome's native Wayland PiP sometimes has an empty app_id instead of
        # inheriting the parent browser class. Its standard title is then the
        # only reliable identifier; associate it with the browser on that output.
        if (index is None and app_id == '' and node.get('name') == 'Picture in picture'
                and node.get('shell') == 'xdg_shell'):
            index = indexes_by_output.get(output)
        geometry = node.get('geometry')
        if (node.get('type') in ('con', 'floating_con') and index in groups
                and isinstance(node.get('id'), int) and node['id'] > 0
                and isinstance(geometry, dict)
                and all(isinstance(geometry.get(key), int) and geometry[key] > 0
                        for key in ('width', 'height'))):
            groups[index].append(node)
        for key in ('nodes', 'floating_nodes'):
            if isinstance(node.get(key), list):
                stack.extend((child, output) for child in node[key])

    result = []
    for index, windows in groups.items():
        if len(windows) < 2:
            continue
        main = max(windows, key=lambda node: node['geometry']['width'] * node['geometry']['height'])
        width, height = main['geometry']['width'], main['geometry']['height']
        if width < 800 or height < 600:
            continue
        for node in windows:
            if node is main:
                continue
            small = node['geometry']
            if not (small['width'] <= width * 0.65 and small['height'] <= height * 0.8
                    and small['width'] * small['height'] <= width * height * 0.5):
                continue
            if node.get('type') == 'con' and node.get('floating') in ('auto_off', 'user_off'):
                result.append((index, node))
            elif node.get('type') == 'floating_con' and node.get('floating') in ('auto_on', 'user_on'):
                rect = node.get('rect')
                if (isinstance(rect, dict) and isinstance(rect.get('width'), int)
                        and isinstance(rect.get('height'), int)
                        and (rect['width'] > small['width'] * 1.15
                             or rect['height'] > small['height'] * 1.15)):
                    result.append((index, node))
    return result


def float_auxiliary_windows(tree, desired, outputs):
    active = {item.get('name'): item.get('rect') for item in outputs
              if isinstance(item, dict) and item.get('active') is True}
    for index, node in auxiliary_windows(tree, desired):
        container_id = node['id']
        criteria = f'[con_id={container_id}]'
        commands = ([f'{criteria} fullscreen disable', f'{criteria} floating enable']
                    if node['type'] == 'con' else [])
        width = node['geometry']['width']
        height = node['geometry']['height']
        output = desired[index].get('output')
        rect = active.get(output)
        position = None
        if (isinstance(output, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', output)
                and isinstance(rect, dict)
                and all(isinstance(rect.get(key), int) for key in ('x', 'y', 'width', 'height'))
                and rect['width'] > 0 and rect['height'] > 0):
            x = max(rect['x'] + 16, rect['x'] + rect['width'] - width - 16)
            y = rect['y'] + 16
            position = (x, y)
            commands.append(f'{criteria} move container to output "{output}"')
        commands.append(f'{criteria} resize set width {width} px height {height} px')
        if position is not None:
            commands.append(f'{criteria} move absolute position {x} px {y} px')
        try:
            response = subprocess.run(['swaymsg', '-r', '; '.join(commands)],
                capture_output=True, text=True, check=True, timeout=5)
            if not all(item.get('success') for item in json.loads(response.stdout)):
                return False
        except (OSError, subprocess.SubprocessError, ValueError, TypeError):
            return False
    return True


def reconcile_auxiliary_windows(desired, outputs):
    try:
        response = subprocess.run(['swaymsg', '-r', '-t', 'get_tree'], capture_output=True,
                                  text=True, check=True, timeout=5)
        return float_auxiliary_windows(json.loads(response.stdout), desired, outputs)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return False


def start_window_events():
    try:
        return subprocess.Popen(['swaymsg', '-m', '-r', '-t', 'subscribe', '["window"]'],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        return None


def install_picture_in_picture_rule():
    """Float classless Chrome PiP before its first tiled frame is drawn."""
    criteria = '[app_id="^$" title="^Picture in picture$"]'
    commands = (f'for_window {criteria} floating enable; '
                f'for_window {criteria} move position 84 ppt 2 ppt')
    try:
        response = subprocess.run(['swaymsg', '-r', commands], capture_output=True,
                                  text=True, check=True, timeout=5)
        return all(item.get('success') for item in json.loads(response.stdout))
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return False


def wait_window_event(stream, timeout):
    readable, _, _ = select.select([stream], [], [], timeout)
    return bool(readable and os.read(stream.fileno(), 65536))


def place_view(view, future=False):
    """Assign a future or existing managed window to its configured output."""
    criteria = f'[app_id="elderbrain-view-{view["index"]}"]'
    prefix = 'for_window ' if future else ''
    commands = (f'{prefix}{criteria} move container to output "{view["output"]}"; '
                f'{prefix}{criteria} fullscreen {"enable" if view["mode"] == "player" else "disable"}')
    try:
        response = subprocess.run(['swaymsg', '-r', commands], capture_output=True,
                                  text=True, check=True, timeout=5)
        return all(item.get('success') for item in json.loads(response.stdout))
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return False


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
    cursor_signature = None
    status_file = Path(os.environ['XDG_RUNTIME_DIR']) / 'beamer-status.json'
    runtime = Path(os.environ['XDG_RUNTIME_DIR'])
    running = True

    def stop(_signal, _frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if not install_picture_in_picture_rule():
        print('Unable to install PiP first-frame floating rule', flush=True)
    window_events = start_window_events()
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
            if apply_output_modes(desired, outputs):
                time.sleep(2)
                continue
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
                        state = statuses.get(index, {}).get('state', 'unavailable')
                        retry_after[index] = (view.get('beamerRevision'),
                                              next_retry(state, time.monotonic()))
                    terminate(child)
                    if view['mode'] == 'player' and child.stdout is not None:
                        if statuses.get(index, {}).get('state') == 'ready':
                            statuses[index] = {'state': 'unavailable', 'revision': view['beamerRevision'], 'observedAt': time.time()}
                        child.stdout.close()
                    del children[index]
                    rules.pop(index, None)
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
                    if not place_view(view, future=True):
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
            placements = window_outputs()
            for index, view in desired.items():
                if index in children and index in placements and placements[index] != view['output']:
                    place_view(view)
            reconcile_auxiliary_windows(desired, outputs)
            target = admin_cursor_target(desired, outputs)
            topology = tuple(sorted(
                (item.get('name'), json.dumps(item.get('rect'), sort_keys=True))
                for item in outputs if item.get('active')))
            signature = (topology, target)
            if (target is not None and signature != cursor_signature
                    and all(index in children for index in desired)
                    and views_mapped(desired)
                    and move_cursor(target)):
                cursor_signature = signature
            report = []
            for index, view in desired.items():
                if view['mode'] == 'player':
                    entry = statuses.get(index) or {}
                    if not credential or entry.get('revision') != credential['revision']:
                        entry = {'state': 'pairing-required' if not credential else 'pending-verification',
                                 'revision': credential['revision'] if credential else None, 'observedAt': time.time()}
                    report.append({'index': index, **entry})
            write_status(status_file, report)
            if window_events is not None and window_events.poll() is None:
                try:
                    if wait_window_event(window_events.stdout, 2):
                        reconcile_auxiliary_windows(desired, outputs)
                except OSError:
                    time.sleep(2)
            else:
                if window_events is not None:
                    window_events.stdout.close()
                window_events = start_window_events()
                time.sleep(2)
    finally:
        if window_events is not None:
            if window_events.poll() is None:
                try:
                    window_events.terminate()
                except ProcessLookupError:
                    pass
            try:
                window_events.wait(timeout=5)
            except subprocess.TimeoutExpired:
                window_events.kill()
                window_events.wait(timeout=5)
            window_events.stdout.close()
        for _view, child in children.values():
            terminate(child)
        status_file.unlink(missing_ok=True)
        os.close(launcher_lock)


if __name__ == '__main__':
    main()
