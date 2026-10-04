"""Project only display settings from private admin state into a kiosk-readable file."""
import json
import os
from pathlib import Path
import pwd
import re
import stat
import tempfile
import subprocess
from display_preview import DisplayPreview
from beamer_runtime import refresh as refresh_beamer


def initialize_audio(*, cards_file=Path('/proc/asound/cards'),
                     state_file=Path('/var/lib/alsa/asound.state'), run=subprocess.run):
    """Unmute unsaved analog Master controls once; preserve later user choices."""
    cards = re.findall(r'^\s*\d+\s+\[([^\]]+)\]', cards_file.read_text(), re.MULTILINE)
    if not cards:
        return []
    saved = set()
    if state_file.exists():
        saved = set(re.findall(r'^state\.([^\s{]+)\s*\{', state_file.read_text(), re.MULTILINE))
    initialized = []
    for raw_card in cards:
        card = raw_card.strip()
        if card in saved:
            continue
        command = ['amixer', '-c', card, 'sget', 'Master']
        result = run(command, capture_output=True, text=True, timeout=5)
        if result.returncode:
            continue  # HDMI and some other devices have no analog Master control.
        channels = re.findall(r'Playback\s+\d+\s+\[(\d+)%\].*?\[(on|off)\]', result.stdout)
        if not channels:
            continue
        if any(int(volume) == 0 or switch == 'off' for volume, switch in channels):
            command = ['amixer', '-c', card, 'sset', 'Master', '70%', 'unmute']
            result = run(command, capture_output=True, text=True, timeout=5)
            if result.returncode:
                raise RuntimeError(f'Could not initialize audio card {card}')
        result = run(['alsactl', 'store', card], capture_output=True, text=True, timeout=10)
        if result.returncode:
            raise RuntimeError(f'Could not save audio card {card}')
        initialized.append(card)
    return initialized


def project(value):
    return {'configured': value.get('configured') is True,
            'views': [{key: view[key] for key in ('output', 'displayId', 'resolution', 'url', 'mode', 'tabs') if key in view}
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
        initialize_audio()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        # Audio problems must not prevent administration or the visual display.
        print(f'Audio initialization unavailable: {error}', flush=True)
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
