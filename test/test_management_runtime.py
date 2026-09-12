from pathlib import Path
import unittest


class ManagementRuntimeTests(unittest.TestCase):
    def test_bind_mounted_socket_directory_survives_service_restart(self):
        root = Path(__file__).resolve().parents[1]
        unit = (root / 'provisioning/systemd/elderbrain-management.service').read_text()
        self.assertIn('RuntimeDirectory=elderbrain\n', unit)
        self.assertIn('RuntimeDirectoryPreserve=yes\n', unit)
        self.assertIn('- /run/elderbrain:/run/elderbrain', (root / 'compose/compose.yaml').read_text())
