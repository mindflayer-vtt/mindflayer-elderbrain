from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class StorageInstallerTests(unittest.TestCase):
    def test_no_automatic_disk_fallback_and_selection_precedes_storage(self):
        config = yaml.safe_load((ROOT / 'iso/autoinstall/user-data.in').read_text())['autoinstall']
        self.assertEqual(config['storage'], {'config': []})
        self.assertIn('bash /cdrom/elderbrain/iso/select-storage.sh', config['early-commands'])
        self.assertIn('btrfs-progs', config['packages'])
        late = config['late-commands']
        receipt = next(i for i, command in enumerate(late) if command.startswith('install -m 0600 /run/elderbrain-storage-receipt'))
        provision = next(i for i, command in enumerate(late) if 'provisioning/install.sh' in command)
        self.assertLess(receipt, provision)
        self.assertIn('ELDERBRAIN_STORAGE_RECEIPT=', late[provision])

    def test_dedicated_console_and_abort_on_failure(self):
        script = (ROOT / 'iso/select-storage.sh').read_text()
        self.assertIn('set -euo pipefail', script)
        self.assertIn('chvt 3', script)
        self.assertIn('--console /dev/tty3', script)
        self.assertIn('exit 1', script)


if __name__ == '__main__':
    unittest.main()
