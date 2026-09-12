"""Project only display settings from private admin state into a kiosk-readable file."""
import json
import os
from pathlib import Path
import pwd
import stat
import tempfile
import subprocess
from display_preview import DisplayPreview
from beamer_runtime import refresh as refresh_beamer


def project(value):
    return {'configured': value.get('configured') is True,
            'views': [{key: view[key] for key in ('output', 'url', 'mode', 'tabs') if key in view}
                      for view in value.get('views', [])]}


def project_sway(source, directory, group):
    """Copy only compositor settings out of private persistent runtime storage."""
    content = Path(source).read_bytes()
    descriptor, temporary = tempfile.mkstemp(prefix='.sway-', dir=directory)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            os.fchown(stream.fileno(), 0, group)
            os.fchmod(stream.fileno(), 0o640)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, Path(directory) / 'sway.conf')
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    kiosk = pwd.getpwnam('elderbrain-kiosk')
    subprocess.run(['systemctl', 'start', f'user@{kiosk.pw_uid}.service'], check=True, timeout=30)
    try:
        refresh_beamer()
    except (ValueError, OSError):
        # Invalid pairing must not prevent access to the administration browser.
        # refresh removes any stale projected credentials before raising.
        pass
    value = DisplayPreview().effective()
    group = pwd.getpwnam('elderbrain-kiosk').pw_gid
    directory = Path('/run/elderbrain-browser')
    directory.mkdir(mode=0o750, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise RuntimeError('Unsafe browser configuration directory')
    os.chown(directory, 0, group)
    directory.chmod(0o750)
    project_sway('/opt/mindflayer-elderbrain/sway.conf', directory, group)
    descriptor, temporary = tempfile.mkstemp(prefix='.config-', dir=directory)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            os.fchown(stream.fileno(), 0, group)
            os.fchmod(stream.fileno(), 0o640)
            json.dump(project(value), stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / 'config.json')
    finally:
        Path(temporary).unlink(missing_ok=True)


if __name__ == '__main__':
    main()
