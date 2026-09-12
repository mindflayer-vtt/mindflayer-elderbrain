import importlib.util
import json
from pathlib import Path
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('storage_existing', ROOT / 'iso/storage_existing.py')
existing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(existing)
UUID = '4229266e-c564-4bd5-b2db-f4433b5572c5'


class ExistingStorageTests(unittest.TestCase):
    def setUp(self):
        self.commands = []
        self.devices = '1'
        self.marker = Mock(return_value={'identity': 'fixture'})
        self.mount_failure = False

    def command(self, arguments, **kwargs):
        self.commands.append(arguments)
        output = ''
        if arguments[0] == 'blkid':
            output = f'TYPE=btrfs\nUUID={UUID}\n'
        elif arguments[0] == 'btrfs':
            output = f'num_devices\t{self.devices}\n'
        elif arguments[0] == 'mount' and self.mount_failure:
            raise subprocess.TimeoutExpired(arguments, 30)
        elif arguments[0] == 'findmnt':
            output = json.dumps({'filesystems': [dict(
                target=arguments[3], fstype='btrfs', fsroot='/', uuid=UUID,
                options='ro,nosuid,nodev,noexec,relatime,subvolid=5')]})
        return SimpleNamespace(stdout=output, returncode=0)

    def inspect(self, directory):
        return existing.read_existing('/dev/vda4', UUID, read_identity=self.marker,
                                      run=self.command, temporary_root=directory,
                                      stat_device=lambda _: SimpleNamespace(st_mode=stat.S_IFBLK))

    def test_readonly_no_log_replay_and_unmount_before_return(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(self.inspect(directory), {'identity': 'fixture'})
            self.assertEqual(list(Path(directory).iterdir()), [])
        mount = next(command for command in self.commands if command[0] == 'mount')
        self.assertIn('rescue=nologreplay', mount[4].split(','))
        self.assertEqual(self.commands[-1][0], 'umount')

    def test_multidevice_volume_is_never_mounted(self):
        self.devices = '2'
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            self.inspect(directory)
        self.assertFalse(any(command[0] == 'mount' for command in self.commands))
        self.marker.assert_not_called()

    def test_marker_failure_still_unmounts(self):
        self.marker.side_effect = ValueError('invalid marker')
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            self.inspect(directory)
        self.assertEqual(self.commands[-1][0], 'umount')

    def test_mount_timeout_attempts_exact_unmount_and_does_not_read(self):
        self.mount_failure = True
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(subprocess.TimeoutExpired):
            self.inspect(directory)
        self.assertEqual(self.commands[-1][0], 'umount')
        self.marker.assert_not_called()

    def test_regular_files_are_rejected_before_commands(self):
        with self.assertRaises(ValueError):
            existing.read_existing('/dev/vda4', UUID, read_identity=self.marker,
                                   run=self.command, stat_device=lambda _: SimpleNamespace(st_mode=stat.S_IFREG))
        self.assertEqual(self.commands, [])


if __name__ == '__main__':
    unittest.main()
