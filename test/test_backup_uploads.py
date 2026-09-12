import io
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "appliance/lib"))
from backup_uploads import UploadStore


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = UploadStore(Path(self.temp.name) / "uploads")

    def test_private_upload_checksum_and_modification_detection(self):
        record = self.store.receive(io.BytesIO(b"test"), 4, reserve_bytes=0)
        archive, checksum = self.store.verify(record["id"])
        self.assertEqual(checksum, record["sha256"])
        self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
        archive.write_bytes(b"evil")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.store.verify(record["id"], checksum)

    def test_truncated_upload_never_publishes_an_archive(self):
        with self.assertRaisesRegex(ValueError, "Truncated"):
            self.store.receive(io.BytesIO(b"x"), 3, reserve_bytes=0)
        self.assertEqual(list(self.store.directory.glob("*.zst")), [])
        self.assertEqual(list(self.store.directory.glob("*.partial")), [])

    def test_limits_and_path_traversal(self):
        with self.assertRaises(ValueError):
            self.store.receive(io.BytesIO(b"large"), 5, max_bytes=4)
        with self.assertRaises(ValueError):
            self.store.path("../../secrets")


if __name__ == "__main__":
    unittest.main()
