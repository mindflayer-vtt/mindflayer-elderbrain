import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('retirement', ROOT / 'provisioning/compat/retire-legacy-browser.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RetirementTests(unittest.TestCase):
    def test_exact_repair_is_preserved_but_no_longer_a_systemd_dropin(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '30-legacy-browser-projection.conf'
            other = Path(directory) / 'custom.conf'
            other.write_text('custom settings')
            self.assertIsNone(module.retire(path))
            path.write_bytes(module.EXPECTED)
            path.chmod(0o640)
            info = path.stat()
            backup = module.retire(path)
            self.assertFalse(path.exists())
            self.assertEqual(backup.read_bytes(), module.EXPECTED)
            self.assertEqual(backup.stat().st_mode, info.st_mode)
            self.assertEqual(backup.stat().st_ino, info.st_ino)
            self.assertNotEqual(backup.suffix, '.conf')
            self.assertEqual(other.read_text(), 'custom settings')
            self.assertIsNone(module.retire(path))

    def test_custom_unsafe_or_symlinked_dropins_are_not_changed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for kind in ('custom', 'writable', 'symlink'):
                path = root / kind
                if kind == 'symlink':
                    path.symlink_to(root / 'missing')
                else:
                    path.write_bytes(b'custom' if kind == 'custom' else module.EXPECTED)
                    path.chmod(0o666 if kind == 'writable' else 0o600)
                with self.subTest(kind=kind), self.assertRaises(RuntimeError):
                    module.retire(path)
                self.assertTrue(os.path.lexists(path))
            self.assertFalse(list(root.glob('*.bak')))

    def test_installer_checks_before_mutation_and_retires_after_new_unit(self):
        script = (ROOT / 'provisioning/install.sh').read_text()
        self.assertLess(script.index('retire-legacy-browser.py" check'), script.index('install -d'))
        self.assertLess(script.index('"$PAYLOAD_DIR/provisioning/systemd/"*.service'), script.index('retire-legacy-browser.py" retire'))
        self.assertLess(script.index('retire-legacy-browser.py" retire'), script.index('systemctl daemon-reload'))
