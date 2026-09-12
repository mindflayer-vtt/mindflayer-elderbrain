import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "appliance/lib"))
from serial_bundle import verify, IMAGES, LIMIT


class SerialBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private, self.public = self.root / "private.pem", self.root / "public.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(self.private)], check=True, capture_output=True)
        subprocess.run(["openssl", "pkey", "-in", str(self.private), "-pubout", "-out", str(self.public)], check=True, capture_output=True)
        self.files = {name: b"fixture" for name in (*IMAGES, "install-rboot.py", "LICENSE")}
        self.manifest = {"format": 1, "type": "mindflayer-serial-install", "version": "1.2.3",
                         "chip": "esp8266", "hardware": "mindflayer-keypad-v1", "flashSize": 0x400000, "deviceProtocol": 3,
                         "preserveSectors": [0x3f9000, 0x3fa000], "files": [
                             {"path": name, "size": len(value), "sha256": hashlib.sha256(value).hexdigest(),
                              **({"address": IMAGES[name][0]} if name in IMAGES else {})}
                             for name, value in self.files.items()]}

    def archive(self, *, mutate=None, extra=None):
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps(self.manifest))
        signature = self.root / "manifest.sig"
        subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(self.private), "-out", str(signature), str(manifest)], check=True, capture_output=True)
        files = {**self.files, "manifest.json": manifest.read_bytes(), "manifest.sig": signature.read_bytes()}
        if mutate:
            mutate(files)
        target = self.root / "bundle.tar.gz"
        with tarfile.open(target, "w:gz") as archive:
            for name, data in files.items():
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
            if extra:
                archive.addfile(extra)
        return target

    def test_valid_signature_layout_and_exact_release(self):
        archive = self.archive()
        manifest, files = verify(archive, self.public, expected_version="1.2.3")
        self.assertEqual(manifest["version"], "1.2.3")
        self.assertEqual(files, self.files)
        with self.assertRaisesRegex(ValueError, "requested release"):
            verify(archive, self.public, expected_version="9.9.9")

    def test_tampering_members_and_signature_rejected(self):
        for name in ("application.bin", "install-rboot.py", "manifest.json", "manifest.sig"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                verify(self.archive(mutate=lambda files: files.update({name: files[name] + b"tampered"})), self.public)
        for name in ("../escape", "manifest.json"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                verify(self.archive(extra=tarfile.TarInfo(name)), self.public)
        link = tarfile.TarInfo("outside")
        link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
        with self.assertRaises(ValueError):
            verify(self.archive(extra=link), self.public)

    def test_even_signed_unsafe_addresses_and_targets_are_rejected(self):
        self.manifest["files"][0]["address"] = 0x3f9000
        with self.assertRaisesRegex(ValueError, "address"):
            verify(self.archive(), self.public)
        self.manifest["format"] = True
        with self.assertRaisesRegex(ValueError, "layout"):
            verify(self.archive(), self.public)

    def test_compression_bomb_is_bounded(self):
        archive = self.root / "bomb.tar.gz"
        archive.write_bytes(gzip.compress(b"x" * (LIMIT + 1)))
        with self.assertRaisesRegex(ValueError, "Expanded"):
            verify(archive, self.public)

    @unittest.skipUnless(os.environ.get("ELDERBRAIN_SERIAL_BUNDLE_BUILDER"), "requires authorized sibling release builder")
    def test_real_sibling_release_builder_contract(self):
        import struct
        payload = b"\x01\x02\x03\x04"
        def ram(initial=0xef):
            checksum = initial
            for value in payload:
                checksum ^= value
            data = struct.pack("<BBBBIII", 0xe9, 1, 2, 0x40, 0x40100000, 0x40100000, len(payload)) + payload
            return data + bytes(15 - len(data) % 16) + bytes([checksum])
        rboot, app = self.root / "rboot.bin", self.root / "app.bin"
        rboot.write_bytes(ram())
        app.write_bytes(struct.pack("<BBBBIII", 0xea, 4, 2, 0x40, 0x40100000, 0, 16) + bytes(16) + ram())
        archive = self.root / "real.tar.gz"
        subprocess.run([sys.executable, os.environ["ELDERBRAIN_SERIAL_BUNDLE_BUILDER"], "1.2.3", "--rboot", str(rboot),
                        "--application", str(app), "--private-key", str(self.private), "--public-key", str(self.public),
                        "--output", str(archive)], check=True, capture_output=True)
        manifest, files = verify(archive, self.public, expected_version="1.2.3")
        self.assertEqual(files["application.bin"], app.read_bytes())
        self.assertEqual(manifest["chip"], "esp8266")
        # Exercise the actual signed installer and image preflight through the
        # host adapter, replacing only the physical esptool transport.
        from serial_install import SerialInstaller
        lock = os.open(self.root / "job.lock", os.O_CREAT | os.O_RDWR, 0o600)
        self.addCleanup(os.close, lock)
        adapter = SerialInstaller(archive, self.public, "1.2.3", self.root / "installation",
                                  python=sys.executable, esptool="unused", resolve_port=lambda: "/dev/mock-keypad",
                                  capabilities={"deviceProtocolVersions": [1, 2, 3], "configurationProof": "sha256-canonical-envelope-v2"},
                                  lock_fd=lock)
        writes = []
        def transport(python, esptool, port, *arguments, capture=False):
            if arguments[0] == "chip_id":
                return "Chip is ESP8266EX\n"
            if arguments[0] == "flash_id":
                return "Detected flash size: 4MB\n"
            if arguments[0] == "read_flash":
                Path(arguments[-1]).write_bytes(bytes([255]) * 4096)
                return ""
            self.assertEqual(arguments[0], "write_flash")
            writes.append(arguments)
            return ""
        adapter.installer.run = transport
        self.assertEqual(adapter.backup(), (bytes([255]) * 4096,) * 2)
        adapter.flash()
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][7::2], ("0x000000", "0x001000", "0x100000", "0x002000"))
        self.assertEqual((adapter.directory / "flash-backup/provisioning-a.bin").read_bytes(), bytes([255]) * 4096)


if __name__ == "__main__":
    unittest.main()
