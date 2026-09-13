import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import time
import unittest

spec = importlib.util.spec_from_file_location("backup_archive", Path(__file__).resolve().parents[1] / "appliance/lib/backup_archive.py")
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        (self.source / "secrets").mkdir(parents=True)
        secret = self.source / "secrets/admin.json"
        secret.write_text('{"secret":"must-survive-backup"}')
        secret.chmod(0o600)
        (self.source / "current").symlink_to("secrets/admin.json")
        self.archive = self.root / "backup.tar.zst"

    def create(self):
        return backup.create(self.archive, {"elderbrain": self.source}, version="test", identity="appliance-test")

    def test_fixed_os_ssh_link_roundtrips_without_allowing_arbitrary_absolute_links(self):
        ssh = self.root / "ssh"
        (ssh / "ssh_config.d").mkdir(parents=True)
        name, target = next(iter(backup.SYSTEM_FILE_LINKS.items()))
        link = ssh / "ssh_config.d/20-systemd-ssh-proxy.conf"
        link.symlink_to(target)
        backup.create(self.archive, {"ssh-server": ssh}, version="test", identity="fixture")
        with backup.stage(self.archive, parent=self.root, restore_ownership=False) as (contents, _):
            self.assertEqual(os.readlink(contents / name), target)
        with self.assertRaises(ValueError):
            backup.safe_link(name, "/etc/shadow")
        with self.assertRaises(ValueError):
            backup.safe_link("ssh-server/other", target)
        with self.assertRaisesRegex(ValueError, "external system file"):
            backup.validate_link_graph([
                {"path": name, "type": "symlink", "target": target},
                {"path": "ssh-server/escape", "type": "symlink", "target": "ssh_config.d/20-systemd-ssh-proxy.conf/../../shadow"},
            ])

    def crafted(self, members):
        plain = self.root / "crafted.tar"
        with tarfile.open(plain, "w") as archive:
            for name, data, kind, target in members:
                info = tarfile.TarInfo(name)
                info.type = kind
                info.linkname = target
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        subprocess.run(["zstd", "-q", str(plain), "-o", str(self.archive)], check=True)

    def test_round_trip_preserves_secrets_permissions_and_identity(self):
        expected = self.create()
        self.assertEqual(backup.validate(self.archive), expected)
        self.assertEqual(self.archive.stat().st_mode & 0o777, 0o600)
        entry = next(e for e in expected["entries"] if e["path"].endswith("admin.json"))
        self.assertEqual(entry["mode"], 0o600)
        self.assertEqual(entry["uid"], os.getuid())
        self.assertTrue(expected["containsSecrets"])
        with self.assertRaises(ValueError):
            self.create()

    def test_browser_runtime_singletons_are_excluded_but_profile_data_is_preserved(self):
        browser = self.root / "browser"
        profile = browser / "profile-0-admin"
        profile.mkdir(parents=True)
        (profile / "Preferences").write_text('{"configured":true}')
        (profile / "SingletonLock").symlink_to("elderbrain-123")
        (profile / "SingletonSocket").symlink_to("/tmp/com.google.Chrome.test/SingletonSocket")
        (profile / "SingletonCookie").symlink_to("123456")
        manifest = backup.create(self.archive, {"browser": browser}, version="test", identity="fixture")
        paths = {entry["path"] for entry in manifest["entries"]}
        self.assertIn("browser/profile-0-admin/Preferences", paths)
        for name in backup.BROWSER_RUNTIME_ENTRIES:
            self.assertNotIn("browser/profile-0-admin/" + name, paths)
        with backup.stage(self.archive, parent=self.root) as (contents, _):
            self.assertEqual((contents / "browser/profile-0-admin/Preferences").read_text(),
                             '{"configured":true}')

    def test_no_recursive_backup_or_missing_source(self):
        with self.assertRaises(ValueError):
            backup.create(self.source / "archive.tar.zst", {"elderbrain": self.source}, version="t", identity="t")
        with self.assertRaises(ValueError):
            backup.create(self.archive, {"elderbrain": self.root / "missing"}, version="t", identity="t")

    def test_expired_attempt_deadline_publishes_no_archive(self):
        with self.assertRaisesRegex(TimeoutError, "time limit"):
            backup.create(self.archive, {"elderbrain": self.source}, version="t", identity="t",
                          deadline=time.monotonic() - 1)
        self.assertFalse(self.archive.exists())

    def test_path_traversal_is_rejected(self):
        self.crafted([("elderbrain/../../outside", b"x", tarfile.REGTYPE, "")])
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            backup.validate(self.archive)
        self.assertFalse((self.root / "outside").exists())

    def test_escaping_symlink_is_rejected(self):
        self.crafted([("elderbrain/link", b"", tarfile.SYMTYPE, "../../etc")])
        with self.assertRaisesRegex(ValueError, "escapes"):
            backup.validate(self.archive)

    def test_checksum_mismatch_is_rejected(self):
        manifest = {"format": 1, "roots": ["elderbrain"], "entries": [],
                    "applianceVersion": "test", "applianceIdentity": "test",
                    "createdAt": "2026-09-10T00:00:00+00:00", "containsSecrets": True}
        self.crafted([("elderbrain/file", b"modified", tarfile.REGTYPE, ""),
                      ("manifest.json", json.dumps(manifest).encode(), tarfile.REGTYPE, "")])
        with self.assertRaisesRegex(ValueError, "checksums"):
            backup.validate(self.archive)

    def test_duplicate_paths_are_rejected(self):
        self.crafted([("elderbrain/file", b"x", tarfile.REGTYPE, "")] * 2)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            backup.validate(self.archive)

    def test_decompression_size_limit(self):
        self.create()
        with self.assertRaisesRegex(ValueError, "limits"):
            backup.validate(self.archive, max_bytes=100)

    def test_stage_restores_bytes_links_permissions_and_cleans_up(self):
        self.create()
        with backup.stage(self.archive, parent=self.root) as (contents, manifest):
            restored = contents / "elderbrain/secrets/admin.json"
            self.assertEqual(restored.read_bytes(), (self.source / "secrets/admin.json").read_bytes())
            self.assertEqual(restored.stat().st_mode & 0o777, 0o600)
            self.assertEqual(restored.stat().st_uid, os.getuid())
            self.assertEqual(os.readlink(contents / "elderbrain/current"), "secrets/admin.json")
            self.assertEqual(backup.preview(manifest)["files"], 1)
            self.assertNotIn("entries", backup.preview(manifest))
        self.assertFalse(contents.exists())

    def test_stage_failure_leaves_no_staging_files(self):
        self.archive.write_bytes(b"not a backup")
        before = set(self.root.iterdir())
        with self.assertRaises((ValueError, tarfile.TarError)):
            with backup.stage(self.archive, parent=self.root):
                self.fail("Invalid archive was staged")
        self.assertEqual(set(self.root.iterdir()), before)

    def test_link_chain_cannot_escape_via_dotdot(self):
        (self.source / "dir").mkdir()
        (self.source / "a").symlink_to(".")
        (self.source / "dir/link").symlink_to("../a/../outside")
        with self.assertRaisesRegex(ValueError, "chain escapes"):
            self.create()

    def test_hardlinked_files_are_independent_archive_files(self):
        os.link(self.source / "secrets/admin.json", self.source / "another")
        self.create()
        with backup.stage(self.archive, parent=self.root) as (contents, _):
            self.assertEqual((contents / "elderbrain/another").read_bytes(),
                             (contents / "elderbrain/secrets/admin.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
