"""Keep storage confirmation visible without taking over recovery consoles."""

from pathlib import Path
import select
import subprocess


def restore_prompt_focus(*, active_path=Path('/sys/class/tty/tty0/active'),
                         run=subprocess.run):
    # Subiquity can switch back to tty1 after early commands have started. Only
    # reclaim that installer console; tty2/other consoles remain available for
    # deliberate operator diagnostics.
    if active_path.read_text().strip() == 'tty1':
        run(['chvt', '3'], check=True, capture_output=True, timeout=5)


def read_line(stream, *, focus=restore_prompt_focus, ready=select.select):
    while True:
        focus()
        readable, _, _ = ready([stream], [], [], 1)
        if readable:
            line = stream.readline()
            if not line:
                raise ValueError('Console closed; installation cancelled')
            return line.rstrip('\r\n')
