"""Per-view user services: systemd owns and cleans the complete browser cgroup."""
import os
import subprocess


def manager_environment():
    return {**os.environ, 'XDG_RUNTIME_DIR': f'/run/user/{os.getuid()}',
            'DBUS_SESSION_BUS_ADDRESS': f'unix:path=/run/user/{os.getuid()}/bus'}


def service_command(index, args, environment):
    if index not in (0, 1):
        raise ValueError('Invalid browser view')
    command = ['/usr/bin/systemd-run', '--user', '--quiet', '--pipe', '--wait', '--collect',
               f'--unit=elderbrain-view-{index}', f'--description=Elderbrain browser view {index}', '--property=KillMode=control-group',
               '--property=TimeoutStopSec=5s']
    for name in ('XDG_RUNTIME_DIR', 'WAYLAND_DISPLAY', 'DISPLAY', 'XDG_SESSION_TYPE'):
        if name in environment:
            command.append(f'--setenv={name}={environment[name]}')
    return [*command, '--', *args]


def launch(index, args, *, stdin=None, stdout=subprocess.DEVNULL):
    child = subprocess.Popen(service_command(index, args, os.environ), stdin=stdin,
                             stdout=stdout, stderr=subprocess.DEVNULL,
                             env=manager_environment())
    child.browser_unit = f'elderbrain-view-{index}.service'
    return child


def stop_view(index):
    if index not in (0, 1):
        raise ValueError('Invalid browser view')
    unit = f'elderbrain-view-{index}.service'
    result = subprocess.run(['/usr/bin/systemctl', '--user', 'stop', unit],
                            env=manager_environment(), capture_output=True, timeout=15)
    # Collected units can already be absent. A still-active unit must block replacement.
    state = subprocess.run(['/usr/bin/systemctl', '--user', 'is-active', unit],
                           env=manager_environment(), capture_output=True, timeout=5)
    if state.returncode not in (3, 4) or (result.returncode and state.stdout.strip() not in (b'inactive', b'unknown', b'failed')):
        raise RuntimeError('Browser service cleanup could not be verified')


def terminate(child):
    stop_view(int(child.browser_unit.removeprefix('elderbrain-view-').removesuffix('.service')))
    child.wait(timeout=10)
