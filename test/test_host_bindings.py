import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'appliance/lib'))
from host_bindings import refresh
from restore_service import host_targets


class HostBindingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / 'state'
        self.source = self.state / 'host/ssh-root'
        self.target = self.root / 'root/.ssh'
        self.source.mkdir(parents=True)
        self.target.mkdir(parents=True)
        self.mount = dict(target=str(self.target), fstype='btrfs', uuid='test-uuid',
                          fsroot='/host/ssh-root')

    def execute(self, *, status=0, same=True):
        run = Mock(side_effect=[SimpleNamespace(returncode=status, stdout=json.dumps(
            {'filesystems': [self.mount]})), SimpleNamespace(), SimpleNamespace()])
        with patch.object(Path, 'samefile', return_value=same):
            refresh(self.state, 'test-uuid', ['ssh-root'], host_root=self.root, run=run)
        return [call.args[0] for call in run.call_args_list]

    def test_refresh_current_previous_and_rejected_trees(self):
        for root in ['/host/ssh-root',
                     '/host/.elderbrain-restore-' + 'a'*32 + '-ssh-root/previous',
                     '/host/.elderbrain-restore-' + 'a'*32 + '-ssh-root/rejected']:
            self.mount['fsroot'] = root
            commands = self.execute()
            self.assertEqual([command[0] for command in commands], ['findmnt', 'umount', 'mount'])
            self.assertEqual(commands[1], ['umount', str(self.target)])
            self.assertEqual(commands[2], ['mount', '--bind', str(self.source), str(self.target)])

    def test_missing_mount_after_interruption_is_recreated_without_unmount(self):
        commands = self.execute(status=1)
        self.assertEqual([command[0] for command in commands], ['findmnt', 'mount'])

    def test_unexpected_mounts_are_not_unmounted(self):
        for key, value in [('uuid', 'wrong'), ('fsroot', '/unrelated'), ('fstype', 'ext4')]:
            original = self.mount[key]
            self.mount[key] = value
            run = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(
                {'filesystems': [self.mount]})))
            with self.assertRaises(ValueError):
                refresh(self.state, 'test-uuid', ['ssh-root'], host_root=self.root, run=run)
            self.assertEqual(run.call_count, 1)
            self.mount[key] = original

    def test_wrong_inode_after_bind_fails(self):
        with self.assertRaisesRegex(RuntimeError, 'restored tree'):
            self.execute(same=False)

    def test_persistent_restore_targets_canonical_directories(self):
        runtime = self.root / 'runtime'
        targets = host_targets(self.state, runtime, self.root, persistent=True)
        self.assertEqual(targets['ssh-root'], self.source)
        self.assertEqual(targets['ssh-server'], self.state / 'host/ssh-server')
        self.assertEqual(targets['runtime/appliance.env'], self.state / 'host/runtime/appliance.env')
        self.assertEqual(targets['runtime/sway.conf'], self.state / 'host/runtime/sway.conf')
        self.assertEqual(targets['runtime/compose.yaml'], runtime / 'compose.yaml')
        legacy = host_targets(self.state, runtime, self.root)
        self.assertEqual(legacy['ssh-root'], self.target)


if __name__ == '__main__':
    unittest.main()
