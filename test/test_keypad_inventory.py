import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "appliance/lib"))
from keypad_inventory import registered_keypads, usb_serial_devices, installation_receipts


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "mindflayer").mkdir()
        self.file = self.root / "mindflayer/devices.json"

    def test_completed_installation_projection_excludes_secrets_and_old_job_records(self):
        settings = {"revision": 3, "ssid": "Table", "psk": "private-wifi-password"}
        central = self.root / "elderbrain/secrets/keypad-settings.json"
        central.parent.mkdir(parents=True)
        central.write_text(json.dumps(settings))
        directory = self.root / "keypad-installations" / ("a" * 32)
        directory.mkdir(parents=True)
        result = {"state": "verified", "deviceId": "keypad", "revision": 3, "configurationVerifiedAt": 1234, "configurationDigest": "b" * 64}
        journal = {"state": "completed", "settings": settings, "result": result, "plan": {"secret": "private-device-secret"}}
        record = directory / "installation.json"
        record.write_text(json.dumps(journal))
        receipts = installation_receipts(self.root)
        self.assertEqual(len(receipts), 1)
        self.assertTrue(receipts[0]["matchesCurrentSettings"])
        self.assertNotIn("private-wifi-password", json.dumps(receipts))
        self.assertNotIn("private-device-secret", json.dumps(receipts))
        central.write_text(json.dumps({**settings, "revision": 4}))
        self.assertFalse(installation_receipts(self.root)[0]["matchesCurrentSettings"])
        journal["state"] = "failed"
        record.write_text(json.dumps(journal))
        self.assertEqual(installation_receipts(self.root), [])
        (self.root / "jobs").mkdir()
        (self.root / "jobs/old.json").write_text(json.dumps({**journal, "state": "completed"}))
        self.assertEqual(installation_receipts(self.root), [])

    def test_only_ids_are_projected_including_never_connected_devices(self):
        self.assertEqual(registered_keypads(self.root), [])
        self.file.write_text(json.dumps({"version": 1, "devices": {
            "offline": {"secret": "a" * 64, "unexpected": "private-value"},
            "constructor": {"secret": "b" * 64}}}))
        result = registered_keypads(self.root)
        self.assertEqual(result, ["constructor", "offline"])
        self.assertNotIn("private-value", json.dumps(result))
        self.assertNotIn("a" * 64, json.dumps(result))

    def test_invalid_schema_never_reports_empty_success(self):
        for record in ({"version": 2, "devices": {}}, {"version": 1, "devices": []},
                       {"version": 1, "devices": {"bad/id": {"secret": "a" * 64}}},
                       {"version": 1, "devices": {"id": {"secret": "short"}}}):
            self.file.write_text(json.dumps(record))
            with self.assertRaises(ValueError):
                registered_keypads(self.root)

    def test_symlink_is_rejected(self):
        self.file.symlink_to(self.root / "missing")
        with self.assertRaises(OSError):
            registered_keypads(self.root)

    def test_usb_discovery_is_passive_and_distinguishes_usb_from_chip_identity(self):
        sys_root = self.root / "sys"
        dev_root = self.root / "dev"
        dev_root.mkdir()
        tty = sys_root / "class/tty/ttyUSB0"
        tty.mkdir(parents=True)
        usb = sys_root / "devices/pci/usb1/1-1"
        interface = usb / "1-1:1.0/ttyUSB0"
        interface.mkdir(parents=True)
        (tty / "device").symlink_to(interface)
        for name, value in {"idVendor": "1A86", "idProduct": "7523", "product": "Serial adapter", "serial": "fixture"}.items():
            (usb / name).write_text(value)
        # /dev/null supplies a real character-device stat, with no serial I/O.
        (dev_root / "ttyUSB0").symlink_to("/dev/null")
        found = usb_serial_devices(sys_root, dev_root)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["vendorId"], "1a86")
        self.assertFalse(found[0]["chipVerified"])
        self.assertEqual(found, usb_serial_devices(sys_root, dev_root))
        (dev_root / "ttyUSB0").unlink()
        self.assertEqual(usb_serial_devices(sys_root, dev_root), [])
        (dev_root / "ttyUSB0").write_text("not a device")
        self.assertEqual(usb_serial_devices(sys_root, dev_root), [])

    def test_usb_discovery_rejects_sysfs_escape(self):
        sys_root = self.root / "sys"
        tty = sys_root / "class/tty/ttyACM0"
        tty.mkdir(parents=True)
        (tty / "device").symlink_to(self.root)
        self.assertEqual(usb_serial_devices(sys_root, self.root), [])
