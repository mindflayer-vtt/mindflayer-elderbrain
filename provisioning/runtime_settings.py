"""Keep mutable runtime settings on verified data storage, not the OS volume."""

import argparse
import json
import os
from pathlib import Path
import stat
import tempfile
from uuid import uuid4

FILES = {'appliance.env': ('config/defaults/appliance.env', 0o600),
         'sway.conf': ('provisioning/graphics/sway.conf', 0o644)}


def regular(path):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('Runtime setting must be a regular file')


def configure(payload, runtime, state, *, mode):
    if mode not in ('fresh', 'preserve'):
        raise ValueError('Explicit runtime-settings initialization mode required')
    payload, runtime, state = map(Path, (payload, runtime, state))
    destination = state / 'host/runtime'
    if mode == 'fresh':
        destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    if destination.resolve() != destination or not destination.is_dir():
        raise ValueError('Persistent runtime settings directory is missing or unsafe')
    runtime.mkdir(mode=0o755, parents=True, exist_ok=True)
    for name, (default, permissions) in FILES.items():
        canonical, alias = destination / name, runtime / name
        if not canonical.exists() and not canonical.is_symlink() and mode == 'fresh':
            source = alias if alias.exists() or alias.is_symlink() else payload / default
            regular(source)
            fd, temporary = tempfile.mkstemp(prefix='.runtime-default-', dir=destination)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    os.fchmod(stream.fileno(), permissions)
                    stream.write(source.read_bytes())
                    stream.flush()
                    os.fsync(stream.fileno())
                os.link(temporary, canonical)
            finally:
                Path(temporary).unlink(missing_ok=True)
        regular(canonical)  # preserve mode never substitutes defaults
        if alias.is_symlink():
            if os.readlink(alias) != str(canonical):
                raise ValueError('Unexpected runtime configuration symlink')
            continue
        if alias.exists():
            regular(alias)
            if alias.read_bytes() != canonical.read_bytes():
                raise ValueError('OS runtime settings conflict with persistent settings')
        # Atomic alias publication; rename-based future restores target canonical
        # files, so each reader sees the current file through this stable link.
        temporary = runtime / ('.' + name + '.' + uuid4().hex + '.persistent-link')
        os.symlink(str(canonical), temporary)
        try:
            os.replace(temporary, alias)
        finally:
            temporary.unlink(missing_ok=True)
    for directory in (destination, runtime):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--payload', required=True)
    parser.add_argument('--receipt')
    args = parser.parse_args()
    from appliance.lib.storage_guard import check
    check()
    mode = 'preserve'
    if args.receipt:
        mode = json.loads(Path(args.receipt).read_text())['mode']
    configure(args.payload, '/opt/mindflayer-elderbrain', '/var/lib/mindflayer-elderbrain', mode=mode)


if __name__ == '__main__':
    main()
