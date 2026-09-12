from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "appliance/lib"))
from installation_backend import InstallationBackend


class InstallationBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "serial-venv/bin").mkdir(parents=True)
        (self.root / "serial-venv/bin/python").touch()
        (self.root / "esptool-runner.py").touch()
        self.backend = InstallationBackend(self.root, 123)
        self.backend._call = Mock(return_value={"deviceProtocolVersions": [1, 2, 3], "configurationProof": "sha256-canonical-envelope-v2"})
        self.request = {"usbId": "a" * 32, "version": "1.2.3"}
        self.device = {"id": "a" * 32, "port": "/dev/ttyUSB0", "serial": "adapter", "vendorId": "1234", "productId": "1234"}

    def test_incompatible_server_prevents_download_and_usb_access(self):
        self.backend._call.return_value = {"deviceProtocolVersions": [1, 2]}
        with patch("installation_backend.download") as download, patch("installation_backend.usb_serial_devices") as usb:
            with self.assertRaisesRegex(RuntimeError, "Upgrade"):
                self.backend.preflight(self.request, self.root)
            download.assert_not_called()
            usb.assert_not_called()

    def test_download_then_verified_installer_with_revalidated_usb_identity(self):
        with patch("installation_backend.usb_serial_devices", return_value=[self.device]) as usb, patch("installation_backend.download") as download, patch("installation_backend.SerialInstaller") as installer:
            self.backend.preflight(self.request, self.root)
            download.assert_called_once_with("1.2.3", self.root / "release.tar.gz", self.root / "firmware-signing-public.pem")
            resolve = installer.call_args.kwargs["resolve_port"]
            self.assertEqual(resolve(), "/dev/ttyUSB0")
            usb.return_value = [{**self.device, "serial": "replacement"}]
            with self.assertRaisesRegex(RuntimeError, "changed"):
                resolve()
            self.assertEqual(installer.call_args.kwargs["lock_fd"], 123)

    def test_serial_delivery_rechecks_selected_port(self):
        serial = Mock(port="/dev/ttyUSB0", resolve_port=Mock(return_value="/dev/ttyUSB1"))
        with patch("installation_backend.provision") as deliver:
            with self.assertRaisesRegex(RuntimeError, "changed"):
                self.backend.provision(serial, b"envelope")
            deliver.assert_not_called()


if __name__ == "__main__":
    unittest.main()
