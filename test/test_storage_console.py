import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from iso.storage_console import restore_prompt_focus, read_line


class StorageConsoleTests(unittest.TestCase):
    def test_only_installer_console_is_reclaimed(self):
        with tempfile.TemporaryDirectory() as directory:
            active = Path(directory) / 'active'
            for tty in ('tty1', 'tty2', 'tty3', 'tty4'):
                active.write_text(tty + '\n')
                run = Mock()
                restore_prompt_focus(active_path=active, run=run)
                self.assertEqual(run.call_count, int(tty == 'tty1'))
                if tty == 'tty1':
                    self.assertEqual(run.call_args.args[0], ['chvt', '3'])

    def test_focus_rechecked_while_waiting_and_line_preserved(self):
        stream = io.StringIO('ERASE test-disk\n')
        ready = Mock(side_effect=[([], [], []), ([stream], [], [])])
        focus = Mock()
        self.assertEqual(read_line(stream, focus=focus, ready=ready), 'ERASE test-disk')
        self.assertEqual(focus.call_count, 2)

    def test_closed_console_aborts(self):
        stream = io.StringIO('')
        with self.assertRaises(ValueError):
            read_line(stream, focus=Mock(), ready=lambda *args: ([stream], [], []))
