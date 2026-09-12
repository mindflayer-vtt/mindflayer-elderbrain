from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from provisioning.host_persistence import seed, merge_fstab, fstab_entries, activate, DIRECTORIES


class HostPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.os_root = self.root / 'os'
        self.state = self.root / 'data'
        self.source = self.os_root / 'etc/netplan'
        self.source.mkdir(parents=True)
        self.state.mkdir()
        self.settings = self.source / '90-user.yaml'
        self.settings.write_text('network: {version: 2}\n')
        self.settings.chmod(0o600)

    def seed(self, mode, **kwargs):
        return seed('netplan', mode=mode, os_root=self.os_root, state_root=self.state, **kwargs)

    def test_fresh_copies_bytes_and_permissions_and_preserve_never_reseeds(self):
        destination = self.seed('fresh')
        info = (destination / self.settings.name).stat()
        self.assertEqual((destination / self.settings.name).read_bytes(), self.settings.read_bytes())
        self.assertEqual(info.st_mode & 0o777, 0o600)
        self.settings.write_text('new installer defaults')
        run = Mock()
        self.assertEqual(self.seed('preserve', run=run), destination)
        run.assert_not_called()
        self.assertEqual((destination / self.settings.name).read_text(), 'network: {version: 2}\n')

    def test_missing_preserved_state_is_fatal(self):
        with self.assertRaises(FileNotFoundError):
            self.seed('preserve')
        self.assertEqual(list(self.state.iterdir()), [])

    def test_fresh_refuses_existing_data(self):
        self.seed('fresh')
        with self.assertRaises(ValueError):
            self.seed('fresh')

    def test_symlinked_state_directory_is_refused(self):
        (self.state / 'host').symlink_to(self.os_root)
        with self.assertRaises(ValueError):
            self.seed('fresh')

    def test_fstab_idempotent_and_unrelated_entries_preserved(self):
        original = 'UUID=os / ext4 defaults 0 1\n'
        merged = merge_fstab(original)
        self.assertTrue(merged.startswith(original))
        self.assertEqual(merge_fstab(merged), merged)
        self.assertNotIn('nofail', merged)
        self.assertIn('x-systemd.requires-mounts-for=', merged)

    def test_conflicting_or_duplicate_mounts_rejected(self):
        with self.assertRaises(ValueError):
            merge_fstab('/dev/other /etc/netplan ext4 defaults 0 0\n')
        with self.assertRaises(ValueError):
            merge_fstab(fstab_entries() + fstab_entries())

    def test_activation_publishes_all_mounts_only_after_complete_seed(self):
        (self.os_root / 'etc/fstab').write_text('UUID=os / ext4 defaults 0 1\n')
        for target in DIRECTORIES.values():
            (self.os_root / target.lstrip('/')).mkdir(parents=True, exist_ok=True)
        bind = Mock()
        activate(mode='fresh', os_root=self.os_root, state_root=self.state,
                 identity={'data_uuid': 'fixture'}, bind=bind)
        self.assertEqual(bind.call_count, len(DIRECTORIES))
        for name in DIRECTORIES:
            self.assertTrue((self.state / 'host' / name).is_dir())
        self.assertIn(fstab_entries(), (self.os_root / 'etc/fstab').read_text())

    def test_missing_preserved_directory_does_not_publish_mount_configuration(self):
        original = 'UUID=os / ext4 defaults 0 1\n'
        (self.os_root / 'etc/fstab').write_text(original)
        bind = Mock()
        with self.assertRaises(FileNotFoundError):
            activate(mode='preserve', os_root=self.os_root, state_root=self.state,
                     identity={'data_uuid': 'fixture'}, bind=bind)
        self.assertEqual((self.os_root / 'etc/fstab').read_text(), original)
        bind.assert_not_called()


if __name__ == '__main__':
    unittest.main()
