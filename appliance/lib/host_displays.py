"""Read-only display catalogue from the dedicated kiosk's Sway session."""
import hashlib
import json
from pathlib import Path
import pwd
import re
import stat
import subprocess
import time


def monitor_id(output):
    identity = '\0'.join(str(output.get(key) or '').strip()[:128]
                         for key in ('make', 'model', 'serial'))
    if not identity.replace('\0', ''):
        return ''
    return 'monitor-' + hashlib.sha256(identity.encode()).hexdigest()


def normalize(outputs):
    identities = [monitor_id(output) for output in outputs]
    result = []
    for output, identity in zip(outputs, identities):
        name = output.get('name', '')
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', name):
            continue
        mode = output.get('current_mode') or {}
        result.append({'name': name,
                       'id': identity if identity and identities.count(identity) == 1 else '',
                       'make': str(output.get('make') or '')[:128],
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
