"""Publish an installation default only when no existing regular file is present."""
import os
from pathlib import Path
import stat
import sys
import tempfile


def existing(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('Installation default target is not a regular file')
    return True


def initialize(path, data):
    if existing(path):
        return False
    descriptor, temporary = tempfile.mkstemp(prefix='.installation-default-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            # Atomic, same-filesystem create-if-absent; never replace a concurrent save.
            os.link(temporary, path)
        except FileExistsError:
            existing(path)
            return False
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return True
    finally:
        Path(temporary).unlink(missing_ok=True)


if __name__ == '__main__':
    if os.geteuid() != 0 or len(sys.argv) != 3:
        raise SystemExit('Requires root, target and source file (or --empty-json)')
    data = b'{}\n' if sys.argv[2] == '--empty-json' else Path(sys.argv[2]).read_bytes()
    initialize(Path(sys.argv[1]), data)
