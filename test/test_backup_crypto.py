from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "appliance/lib"))
from backup_crypto import transform, decrypted


class CryptoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "archive.tar.zst"
        self.source.write_bytes(b"test-secret-backup-content" * 100)
        self.encrypted = self.root / "archive.tar.zst.gpg"
        self.password = "test-only-export-passphrase"

    def test_gpg_roundtrip_is_private_and_cleans_plaintext_stage(self):
        transform(self.source, self.encrypted, self.password)
        self.assertNotIn(b"test-secret-backup-content", self.encrypted.read_bytes())
        self.assertEqual(self.encrypted.stat().st_mode & 0o777, 0o600)
        with decrypted(self.encrypted, self.password, parent=self.root) as plain:
            self.assertEqual(plain.read_bytes(), self.source.read_bytes())
        self.assertFalse(plain.exists())

    def test_wrong_password_and_corruption_never_publish_plaintext(self):
        transform(self.source, self.encrypted, self.password)
        output = self.root / "decrypted"
        with self.assertRaisesRegex(ValueError, "decrypt"):
            transform(self.encrypted, output, "wrong-test-password", decrypt=True)
        self.assertFalse(output.exists())
        ciphertext = bytearray(self.encrypted.read_bytes())
        ciphertext[-10] ^= 1
        self.encrypted.write_bytes(ciphertext)
        with self.assertRaisesRegex(ValueError, "verify"):
            transform(self.encrypted, output, self.password, decrypt=True)
        self.assertFalse(output.exists())

    def test_size_limits_and_weak_passwords_are_rejected(self):
        with self.assertRaises(ValueError):
            transform(self.source, self.encrypted, "short")
        transform(self.source, self.encrypted, self.password)
        with self.assertRaises(ValueError):
            transform(self.encrypted, self.root / "oversized", self.password, decrypt=True, max_bytes=10)
        self.assertFalse((self.root / "oversized").exists())


if __name__ == "__main__":
    unittest.main()
