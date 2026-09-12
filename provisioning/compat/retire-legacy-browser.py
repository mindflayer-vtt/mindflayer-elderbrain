"""Retire only the exact temporary Lenovo graphics drop-in; keep a local backup."""
import os
from pathlib import Path
import stat
import sys
import tempfile

DROPIN = Path('/etc/systemd/system/elderbrain-graphics.service.d/30-legacy-browser-projection.conf')
EXPECTED = Path(__file__).with_name('30-legacy-browser-projection.conf').read_bytes()


def check(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o022 or path.read_bytes() != EXPECTED):
        raise RuntimeError('Legacy browser drop-in differs from the known repair; review it before upgrading')
    return True


def retire(path):
    if not check(path):
        return None
    descriptor, name = tempfile.mkstemp(prefix=path.name + '.retired-', suffix='.bak', dir=path.parent)
    os.close(descriptor)
    backup = Path(name)
    try:
        check(path)
        os.replace(path, backup)  # Same directory/filesystem; preserve bytes and metadata.
    except Exception:
        backup.unlink()
        raise
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return backup


if __name__ == '__main__':
    if os.geteuid() != 0 or sys.argv[1:] not in (['check'], ['retire']):
        raise SystemExit('Requires root and check or retire')
    if sys.argv[1] == 'check':
        check(DROPIN)
    else:
        backup = retire(DROPIN)
        if backup:
            print('Retired temporary browser repair; recoverable backup: ' + str(backup))
