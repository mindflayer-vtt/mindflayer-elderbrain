import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "appliance/lib"))
from installation_job import run_installation, run_provisioning, validate_plan


class InstallationJobTests(unittest.TestCase):
    def setUp(self):
        clock = patch("installation_job.time.time", return_value=1800000000)
        clock.start()
        self.addCleanup(clock.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "installation"
        self.request = {"usbId": "a" * 32, "version": "1.2.3", "adopt": False}
        self.settings = {"revision": 3, "ssid": "Table", "psk": "private-wifi-password", "serverHost": "table.local", "serverPort": 10443}
        # The private server validates CBOR; this tests the coordinator's envelope
        # length/CRC/digest contract and sequencing, not firmware schema decoding.
        body = b"MFP1\x01\x00\x01\x01"
        self.envelope = body + zlib.crc32(body).to_bytes(4, "big")
        self.plan = {"action": "initial", "deviceId": "keypad-one", "newCredential": {"id": "keypad-one", "secret": "11" * 32},
                     "envelope": base64.b64encode(self.envelope).decode(), "configurationDigest": hashlib.sha256(self.envelope).hexdigest()}
        self.backend = Mock()
        self.serial = Mock(mac="12:34:56:78:90:ab")
        self.backend.preflight.return_value = self.serial
        self.serial.backup.return_value = (b"a" * 4096, b"b" * 4096)
        self.backend.prepare.return_value = self.plan
        self.backend.verify_online.return_value = {"id": "keypad-one", "connected": True, "deviceAuthenticated": True,
                                                   "hardware": "mindflayer-keypad-v1", "firmware": "1.2.3", "configurationDigest": self.plan["configurationDigest"], "configurationVerifiedAt": 1800000000000}
        self.progress = []

    def run_job(self):
        return run_installation(self.directory, self.request, self.settings, self.backend, self.progress.append)

    def test_complete_sequence_persists_credentials_before_side_effects_and_redacts_public_output(self):
        order = []
        def register(credential):
            journal = json.loads((self.directory / "installation.json").read_text())
            self.assertEqual(journal["plan"], self.plan)
            self.assertEqual(journal["stage"], "register-credential")
            order.append("register")
        self.backend.register.side_effect = register
        self.serial.flash.side_effect = lambda: order.append("flash")
        self.backend.provision.side_effect = lambda *args: order.append("provision")
        result = self.run_job()
        self.assertEqual(order, ["register", "flash", "provision"])
        self.assertEqual(result["state"], "verified")
        self.assertEqual(result["revision"], 3)
        self.assertTrue(result["firmwareWritten"])
        self.assertEqual([entry["stage"] for entry in self.progress], ["preflight", "backup-provisioning", "prepare-provisioning", "register-credential", "flash-firmware", "serial-provisioning", "verify-online", "completed"])
        public = json.dumps([result, self.progress])
        for secret in [self.settings["psk"], self.plan["envelope"], self.plan["newCredential"]["secret"]]:
            self.assertNotIn(secret, public)
        self.assertEqual((self.directory / "installation.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.directory.stat().st_mode & 0o777, 0o700)

    def test_foreign_consent_and_envelope_validation_precede_registration_and_flash(self):
        self.plan["action"] = "adopt"
        with self.assertRaisesRegex(RuntimeError, "prepare-provisioning"):
            self.run_job()
        self.backend.register.assert_not_called()
        self.serial.flash.assert_not_called()
        self.assertEqual(json.loads((self.directory / "installation.json").read_text())["state"], "failed")
        self.plan["configurationDigest"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "digest"):
            validate_plan(self.plan)

    def test_failed_flash_retains_plan_and_does_not_provision_or_claim_completion(self):
        self.serial.flash.side_effect = RuntimeError("private-wifi-password")
        with self.assertRaisesRegex(RuntimeError, "flash-firmware") as raised:
            self.run_job()
        self.assertNotIn("private-wifi-password", str(raised.exception))
        self.backend.provision.assert_not_called()
        self.backend.verify_online.assert_not_called()
        journal = json.loads((self.directory / "installation.json").read_text())
        self.assertEqual(journal["plan"], self.plan)
        self.assertEqual(journal["state"], "failed")
        with self.assertRaises(FileExistsError):
            self.run_job()

    def test_online_serial_ack_is_insufficient_without_matching_authenticated_configuration(self):
        self.backend.verify_online.return_value["deviceAuthenticated"] = False
        with self.assertRaisesRegex(RuntimeError, "verify-online"):
            self.run_job()
        self.assertNotIn({"stage": "completed"}, self.progress)

    def test_preserved_identity_skips_registration(self):
        self.plan.update(action="preserve", newCredential=None)
        self.run_job()
        self.backend.register.assert_not_called()
        self.serial.flash.assert_called_once()

    def test_provision_only_never_calls_firmware_flash_and_still_verifies(self):
        result = run_provisioning(self.directory, self.request, self.settings,
                                  self.backend, self.progress.append)
        self.serial.flash.assert_not_called()
        self.backend.provision.assert_called_once_with(self.serial, self.envelope)
        self.backend.verify_online.assert_called_once_with(
            "keypad-one", "1.2.3", self.plan["configurationDigest"], 1800000000000)
        self.assertFalse(result["firmwareWritten"])
        self.assertEqual(json.loads((self.directory / "installation.json").read_text())["operation"], "provision")
        self.assertEqual([entry["stage"] for entry in self.progress],
                         ["preflight", "backup-provisioning", "prepare-provisioning",
                          "register-credential", "serial-provisioning", "verify-online", "completed"])

    def test_stale_cached_connection_does_not_confirm_new_installation(self):
        self.backend.verify_online.return_value["configurationVerifiedAt"] = 1799999999999
        with self.assertRaisesRegex(RuntimeError, "verify-online"):
            self.run_job()


if __name__ == "__main__":
    unittest.main()
