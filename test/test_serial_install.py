import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "appliance/lib"))
from serial_install import SerialInstaller


class SerialInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lock = os.open(self.root / "job.lock", os.O_CREAT | os.O_RDWR, 0o600)
        self.addCleanup(os.close, self.lock)
        self.capabilities = {"deviceProtocolVersions": [1, 2, 3], "configurationProof": "sha256-canonical-envelope-v2"}
        # Verification has its own real signature/archive tests. This fixture
        # isolates the host adapter's ordering and subprocess lifecycle.
        self.files = {"install-rboot.py": b"def preflight(args): return []\n"}

    def create(self, **options):
        with patch("serial_install.verify", return_value=({"version": "1.2.3", "hardware": "mindflayer-keypad-v1"}, self.files)):
            return SerialInstaller("bundle", "public-key", "1.2.3", self.root / "install",
                                   python=sys.executable, esptool="esptool.py", resolve_port=lambda: "/dev/ttyUSB0",
                                   lock_fd=self.lock, capabilities=options.get("capabilities", self.capabilities))

    def test_rejects_untrusted_bundle_and_incompatible_server_before_usb_access(self):
        with patch("serial_install.verify", side_effect=ValueError("bad signature")):
            with self.assertRaisesRegex(ValueError, "signature"):
                SerialInstaller("bundle", "key", "1.2.3", self.root / "install", python="python", esptool="esptool",
                                resolve_port=Mock(side_effect=AssertionError("USB accessed")), capabilities=self.capabilities, lock_fd=self.lock)
        with self.assertRaisesRegex(ValueError, "Server upgrade"):
            self.create(capabilities={"deviceProtocolVersions": [1, 2]})
        self.assertFalse((self.root / "install").exists())

    def test_private_backup_is_required_and_changed_records_stop_installation(self):
        adapter = self.create()
        with self.assertRaisesRegex(RuntimeError, "Back up"):
            adapter.flash()
        data = {0x3f9000: b"a" * 4096, 0x3fa000: b"b" * 4096}
        def backup(args, address, target):
            target.write_bytes(data[address])
            return hashlib.sha256(data[address]).hexdigest()
        installer = Mock()
        installer.assert_esp8266 = Mock()
        installer.assert_flash_size = Mock()
        installer.PROVISIONING = [(0x3f9000, "a.bin"), (0x3fa000, "b.bin")]
        installer.backup_sector = backup
        adapter.installer = installer
        self.assertEqual(adapter.backup(), tuple(data.values()))
        self.assertEqual((adapter.directory / "original-provisioning").stat().st_mode & 0o777, 0o700)
        self.assertEqual((adapter.directory / "original-provisioning/checksums.json").stat().st_mode & 0o777, 0o600)
        def install(args, images, directory):
            directory.mkdir()
            for address, name in installer.PROVISIONING:
                installer.backup_sector(args, address, directory / name)
            self.fail("Flashing must not follow changed provisioning")
        installer.install.side_effect = install
        data[0x3fa000] = b"c" * 4096
        with self.assertRaisesRegex(RuntimeError, "Provisioning changed"):
            adapter.flash()
        self.assertIs(installer.backup_sector, backup)
        self.assertEqual((adapter.directory / "original-provisioning/b.bin").read_bytes(), b"b" * 4096)

    def test_subprocess_has_private_diagnostics_and_inherits_job_lock(self):
        adapter = self.create()
        def start(command, **kwargs):
            self.assertEqual(kwargs["pass_fds"], (self.lock,))
            self.assertTrue(kwargs["start_new_session"])
            self.assertEqual(command[:6], [sys.executable, "esptool.py", "--chip", "esp8266", "--port", "/dev/ttyUSB0"])
            os.write(kwargs["stdout"].fileno(), b"ESP8266EX\nMAC: 12:34:56:78:90:ab\n")
            return Mock(wait=Mock(return_value=0))
        with patch("serial_install.subprocess.Popen", side_effect=start):
            self.assertEqual(adapter.run(sys.executable, "esptool.py", "/dev/ttyUSB0", "chip_id", capture=True), "ESP8266EX\nMAC: 12:34:56:78:90:ab\n")
        self.assertEqual(adapter.mac, "12:34:56:78:90:ab")
        def guarded(command, **kwargs):
            self.assertEqual(command[2:4], ["--expected-mac", "12:34:56:78:90:ab"])
            os.write(kwargs["stdout"].fileno(), b"ESP8266EX\nMAC: 01:02:03:04:05:06\n")
            return Mock(wait=Mock(return_value=0))
        with patch("serial_install.subprocess.Popen", side_effect=guarded):
            with self.assertRaisesRegex(RuntimeError, "MAC"):
                adapter.run(sys.executable, "esptool.py", "/dev/ttyUSB0", "chip_id", capture=True)
        self.assertEqual((adapter.directory / "serial.stdout").stat().st_mode & 0o777, 0o600)
        adapter.resolve_port = lambda: "/dev/ttyUSB1"
        with patch("serial_install.subprocess.Popen") as start:
            with self.assertRaisesRegex(RuntimeError, "USB target changed"):
                adapter.run("python", "esptool", "/dev/ttyUSB0", "write_flash")
            start.assert_not_called()

    def test_timeout_kills_and_reaps_flasher_process_group(self):
        adapter = self.create()
        process = Mock(pid=12345, wait=Mock(side_effect=[subprocess.TimeoutExpired("esptool", 180), 0]))
        with patch("serial_install.subprocess.Popen", return_value=process), patch("serial_install.os.killpg") as kill:
            with self.assertRaises(subprocess.TimeoutExpired):
                adapter.run("python", "esptool", "/dev/ttyUSB0", "write_flash")
            kill.assert_called_once()
            self.assertEqual(kill.call_args.args[0], 12345)
            self.assertEqual(process.wait.call_count, 2)


if __name__ == "__main__":
    unittest.main()
