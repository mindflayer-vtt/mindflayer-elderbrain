"""Dedicated local tty2 bootstrap display; never emit secrets to the journal."""
import os
from pathlib import Path
import re
import stat
import time

PASSWORD = Path('/var/lib/mindflayer-elderbrain/elderbrain/secrets/initial-password')
CLEAR = '\033[3J\033[2J\033[H'


def read_password(path=PASSWORD, owners=(0, 1000)):
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor) as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid not in owners or info.st_mode & 0o077 or not 24 <= info.st_size <= 257:
                return None
            value = source.read(258).strip()
            return value if re.fullmatch(r'[A-Za-z0-9_+/=-]{24,256}', value) else None
    except (OSError, UnicodeError):
        return None


def render(password):
    header = CLEAR + 'Elderbrain administration\n\n'
    if password:
        body = 'First login / root recovery\nUsername: admin\nPassword: ' + password + '\n\nChange this temporary password on first login.\n'
    else:
        body = 'No temporary administrator password is available.\nUse your configured password in the browser.\nDuring first boot, wait for password preparation to finish.\n'
    return header + body + '\nCtrl+Alt+F1: setup browser\nCtrl+Alt+F3: shell login (authentication required)\n'


def main():
    # Open the physical terminal directly, not stdout/stderr inherited by systemd.
    with open('/dev/tty2', 'w', buffering=1) as terminal:
        previous = object()
        try:
            while True:
                password = read_password()
                if password != previous:
                    terminal.write(render(password))
                    terminal.flush()
                    previous = password
                time.sleep(1)
        finally:
            terminal.write(CLEAR)
            terminal.flush()


if __name__ == '__main__':
    main()
