import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('defaults', ROOT / 'provisioning/initialize-default.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class InstallationDefaultsTests(unittest.TestCase):
    def test_preserve_install_never_overwrites_saved_traefik_tls_settings(self):
        script = (ROOT / 'provisioning/install.sh').read_text()
        self.assertIn('initialize-default.py" "$STATE/traefik/admin-tls.yaml"', script)
        self.assertNotIn('install -m 0644 "$PAYLOAD_DIR/config/defaults/admin-tls.yaml"', script)

    def test_foundry_data_is_owned_by_the_container_user(self):
        script = (ROOT / 'provisioning/install.sh').read_text()
        self.assertIn('chown -hR 1000:1000 "$STATE/foundry"', script)
        self.assertIn('chmod u+rwx "$STATE/foundry"', script)
        self.assertLess(script.index('chown -hR 1000:1000 "$STATE/foundry"'),
                        script.index('systemctl enable ssh docker'))

    def test_first_install_is_private_and_existing_bytes_and_metadata_survive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config'
            self.assertTrue(module.initialize(path, b'private configuration'))
            info = path.stat()
            self.assertEqual(info.st_mode & 0o777, 0o600)
            self.assertFalse(module.initialize(path, b'{}'))
            self.assertEqual(path.read_bytes(), b'private configuration')
            self.assertEqual(path.stat(), info)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_symlinks_and_nonfiles_fail_without_following_or_replacing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'original'
            target.write_bytes(b'unchanged')
            for name, destination in [('link', target), ('dangling', root / 'absent')]:
                path = root / name
                path.symlink_to(destination)
                with self.assertRaises(ValueError):
                    module.initialize(path, b'bad')
                self.assertTrue(path.is_symlink())
            with self.assertRaises(ValueError):
                module.initialize(root, b'bad')
            self.assertEqual(target.read_bytes(), b'unchanged')

    def test_concurrent_save_wins_without_being_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config'
            link = os.link
            def concurrent(source, destination):
                path.write_bytes(b'concurrent user settings')
                link(source, destination)
            with patch.object(module.os, 'link', side_effect=concurrent):
                self.assertFalse(module.initialize(path, b'default'))
            self.assertEqual(path.read_bytes(), b'concurrent user settings')
            self.assertEqual(list(Path(directory).iterdir()), [path])
