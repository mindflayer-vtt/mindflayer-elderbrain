"""Targeted compatibility repair for the first hardware ISO's shell launcher.

Not used by new installations: their prepare-browser.py supports display previews.
Run as root before Sway; never make the private administration config readable.
"""
import json
import os
from pathlib import Path
import pwd
import re
import stat
import tempfile
from urllib.parse import urlsplit

SOURCE = Path('/var/lib/mindflayer-elderbrain/elderbrain/config.json')
DIRECTORY = Path('/run/elderbrain-legacy-browser')
SETUP = 'https://127.0.0.1/elderbrain/'


def project(value):
    if not isinstance(value, dict):
        raise ValueError('Invalid display configuration')
    views = value.get('views', [])
    if not isinstance(views, list):
        raise ValueError('Invalid display configuration')
    result = []
    for view in views[:2]:
        if not isinstance(view, dict):
            raise ValueError('Invalid display configuration')
        url, output = view.get('url', SETUP), view.get('output', '')
        if not isinstance(url, str) or any(ord(char) < 32 for char in url):
            raise ValueError('Invalid display URL')
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError('Invalid display URL')
        if not isinstance(output, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{0,128}', output):
            raise ValueError('Invalid display output')
        result.append({'url': url, 'output': output})
    return {'configured': value.get('configured') is True, 'views': result}


def main():
    if os.geteuid() != 0:
        raise RuntimeError('Root preparation required')
    try:
        with SOURCE.open() as stream:
            value = json.load(stream)
    except FileNotFoundError:
        value = {'configured': False}
    payload = project(value)
    group = pwd.getpwnam('elderbrain-kiosk').pw_gid
    DIRECTORY.mkdir(mode=0o750, exist_ok=True)
    info = DIRECTORY.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise RuntimeError('Unsafe projection directory')
    os.chown(DIRECTORY, 0, group)
    DIRECTORY.chmod(0o750)
    descriptor, temporary = tempfile.mkstemp(prefix='.config-', dir=DIRECTORY)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            os.fchown(stream.fileno(), 0, group)
            os.fchmod(stream.fileno(), 0o640)
            json.dump(payload, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, DIRECTORY / 'config.json')
    finally:
        Path(temporary).unlink(missing_ok=True)


if __name__ == '__main__':
    main()
