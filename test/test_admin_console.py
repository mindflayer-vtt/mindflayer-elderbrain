import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('admin_console', ROOT / 'provisioning/admin-console.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AdminConsoleTests(unittest.TestCase):
    def test_private_password_lifecycle_and_unsafe_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'password'
            self.assertIsNone(module.read_password(path))
            value = 'apple-river-tree-stone'
            path.write_text(value + '\n')
            path.chmod(0o600)
            owners = (os.getuid(),)
            self.assertEqual(module.read_password(path, owners), value)
            self.assertIn(value, module.render(module.read_password(path, owners)))
            legacy = 'apple-river-tree-stone-light-moon-green-field'
            path.write_text(legacy + '\n')
            self.assertEqual(module.read_password(path, owners), legacy)
            path.chmod(0o644)
            self.assertIsNone(module.read_password(path, owners))
            path.chmod(0o600)
            path.write_text(value + '\033[2J')
            self.assertIsNone(module.read_password(path, owners))
            path.unlink()
            self.assertNotIn(value, module.render(module.read_password(path)))
            self.assertTrue(module.render(None).startswith(module.CLEAR))
            path.symlink_to('/dev/null')
            self.assertIsNone(module.read_password(path))
            path.unlink()
            os.mkfifo(path, 0o600)
            self.assertIsNone(module.read_password(path))

    def test_console_is_not_a_getty_or_journal_password_printer(self):
        unit = (ROOT / 'provisioning/systemd/elderbrain-admin-console.service').read_text()
        self.assertIn('StandardOutput=null', unit)
        self.assertIn('TTYVTDisallocate=yes', unit)
        installer = (ROOT / 'provisioning/install.sh').read_text()
        self.assertIn('systemctl mask getty@tty2.service autovt@tty2.service', installer)
        self.assertIn('elderbrain-graphics elderbrain-admin-console', installer)
        self.assertNotIn('> /dev/tty2', (ROOT / 'provisioning/prepare-admin').read_text())
