"""Read-only display catalogue from the dedicated kiosk's Sway session."""
import json
from pathlib import Path
import pwd
import re
import stat
import subprocess
import time


def normalize(outputs):
    result = []
    for output in outputs:
        name = output.get('name', '')
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', name):
            continue
        mode = output.get('current_mode') or {}
        result.append({'name': name, 'make': str(output.get('make') or '')[:128],
                       'model': str(output.get('model') or '')[:128],
                       'active': output.get('active') is True,
                       'width': mode.get('width'), 'height': mode.get('height'),
                       'refresh': mode.get('refresh'), 'scale': output.get('scale')})
    return result


def discover():
    uid = pwd.getpwnam('elderbrain-kiosk').pw_uid
    runtime = Path(f'/run/user/{uid}')
    sockets = [path for path in runtime.glob('sway-ipc.*.sock')
               if stat.S_ISSOCK(path.lstat().st_mode) and path.lstat().st_uid == uid]
    if len(sockets) != 1:
        raise ValueError('Kiosk display session unavailable')
    response = subprocess.run(['runuser', '-u', 'elderbrain-kiosk', '--', 'swaymsg', '-s', str(sockets[0]), '-r', '-t', 'get_outputs'],
                              capture_output=True, text=True, check=True, timeout=5)
    return {'at': time.time(), 'outputs': normalize(json.loads(response.stdout))}
