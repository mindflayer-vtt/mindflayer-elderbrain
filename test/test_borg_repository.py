import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "appliance/lib"))
from borg_repository import BorgRepository


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = BorgRepository(self.root, self.root / "runtime", identity="test-id", mountpoint=self.root / "nfs")
        self.repo.settings.configure({"kind": "nfs", "host": "nas", "export": "/backups", "repository": "elderbrain"})

    def test_nfs_rejects_wrong_or_local_mount(self):
        for kind, source in (("ext4", "/dev/sda"), ("nfs4", "wrong:/export")):
            result = SimpleNamespace(returncode=0, stdout=json.dumps({"filesystems": [{"fstype": kind, "source": source, "target": str(self.repo.mountpoint)}]}))
            with patch.object(self.repo, "run", return_value=result), self.assertRaisesRegex(ValueError, "fallback"):
                self.repo.ensure_nfs(self.repo.settings.read())

    def test_missing_mount_is_mounted_and_verified(self):
        expected = SimpleNamespace(returncode=0, stdout=json.dumps({"filesystems": [{"fstype": "nfs4", "source": "nas:/backups", "target": str(self.repo.mountpoint)}]}))
        with patch.object(self.repo, "run", side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=0), expected]) as run:
            self.repo.ensure_nfs(self.repo.settings.read())
            self.assertEqual(run.call_args_list[1].args[0], ["mount", "-t", "nfs", "-o", "hard,nodev,nosuid,noexec", "nas:/backups", str(self.repo.mountpoint)])

    def test_backup_never_prunes_if_create_fails(self):
        (self.root / "backups").mkdir()
        archive = self.root / "backups" / ("elderbrain-" + "a" * 32 + ".tar.zst")
        archive.write_bytes(b"fixture")
        manifest = {"format": 1, "applianceVersion": "test", "applianceIdentity": "test-id",
                    "createdAt": "2026-01-01T00:00:00+00:00", "containsSecrets": True,
                    "roots": ["foundry"], "entries": []}
        with patch.object(self.repo, "prepare"), patch("borg_repository.backup_archive.validate", return_value=manifest), \
                patch.object(self.repo, "action", side_effect=RuntimeError("repository unavailable")) as action:
            with self.assertRaises(RuntimeError):
                self.repo.backup(lambda deadline: {"archive": str(archive)})
            self.assertEqual(action.call_args_list[0].args, ("create",))
            self.assertIn("deadline", action.call_args_list[0].kwargs)
            self.assertEqual(action.call_count, 1)

    def test_transfer_revalidates_exact_local_archive_before_repository_write(self):
        (self.root / "backups").mkdir()
        archive = self.root / "backups" / ("elderbrain-" + "a" * 32 + ".tar.zst")
        archive.write_bytes(b"corrupt")
        with patch.object(self.repo, "prepare"), \
                patch("borg_repository.backup_archive.validate", side_effect=ValueError("corrupt")), \
                patch.object(self.repo, "action") as action:
            with self.assertRaisesRegex(ValueError, "corrupt"):
                self.repo.transfer({"archive": str(archive)})
        action.assert_not_called()

    def test_one_deadline_is_shared_by_prepare_capture_and_all_actions(self):
        deadline = 1234.5
        snapshot = {"archive": str(self.root / "backups" / ("elderbrain-" + "a" * 32 + ".tar.zst"))}
        with patch.object(self.repo, "deadline", return_value=deadline), \
                patch.object(self.repo, "prepare") as prepare, \
                patch.object(self.repo, "transfer_locked", return_value={"state": "completed"}) as transfer:
            seen = []
            self.repo.backup(lambda value: seen.append(value) or snapshot)
        prepare.assert_called_once_with(deadline=deadline)
        transfer.assert_called_once_with(snapshot, deadline=deadline)
        self.assertEqual(seen, [deadline])

    def test_initialize_requires_borg_one_and_requests_encryption(self):
        with patch.object(self.repo, "prepare"), patch.object(self.repo, "run", return_value=SimpleNamespace(stdout="borg 1.4.3")), patch.object(self.repo, "action") as action:
            self.assertEqual(self.repo.initialize()["state"], "initialized")
            action.assert_called_once_with("repo-create", "--encryption", "repokey-blake2")

    def test_archive_list_filters_names_and_extract_rejects_injection(self):
        response = [{"archives": [{"name": "elderbrain-test-2026", "id": "abc", "time": "2026"}, {"name": "--option"}]}]
        with patch.object(self.repo, "prepare"), patch.object(self.repo, "action", return_value=SimpleNamespace(stdout=json.dumps(response))) as action:
            self.assertEqual(self.repo.list_archives(), [{"name": "elderbrain-test-2026", "id": "abc", "time": "2026", "applianceIdentity": "unknown", "applianceVersion": "unknown"}])
            action.assert_called_once_with("repo-list", "--json", "--match-archives", "sh:elderbrain-*")
        with self.assertRaises(ValueError):
            self.repo.fetch_archive("--option")

    def test_recovery_kit_contains_independent_credentials_in_private_artifact(self):
        self.repo.runtime.mkdir()
        (self.repo.runtime / "VERSION").write_text("test-version")

        def export(*arguments):
            self.assertEqual(arguments[:3], ("key", "export", "--path"))
            Path(arguments[3]).write_text("exported-borg-test-key")

        with patch.object(self.repo, "prepare", return_value={"repositories": [{"path": "/mnt/elderbrain-backup/elderbrain"}]}), patch.object(self.repo, "action", side_effect=export):
            result = self.repo.recovery_kit()
        artifact = Path(result["archive"])
        kit = json.loads(artifact.read_text())
        self.assertEqual(artifact.stat().st_mode & 0o777, 0o600)
        self.assertEqual(kit["settings"]["passphrase"], self.repo.settings.read()["passphrase"])
        self.assertEqual(kit["borgRepositoryKey"], "exported-borg-test-key")
        self.assertEqual(kit["applianceVersion"], "test-version")
        self.assertTrue(kit["instructions"])
        self.assertNotIn("passphrase", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
