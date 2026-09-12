from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from backup_pending import PendingBackup, protect, protect_update, public_status
from borg_settings import BorgSettings


class PendingBackupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.state = Path(temporary.name)
        self.runtime = self.state / "runtime"
        self.runtime.mkdir()
        self.snapshots = Mock()
        self.snapshots.create.return_value = {"id": "c" * 32}
        self.snapshots.pinned_records.return_value = [{
            "pin": {"id": "c" * 32, "owner": "a" * 32, "purpose": "pending-backup"},
            "checkpoint": {"id": "c" * 32, "reason": "before-shutdown", "createdAt": 123},
        }]
        self.repository = Mock()
        self.repository.deadline.side_effect = lambda: time.monotonic() + 300
        self.owner = "a" * 32
        self.archive = self.state / "backups" / ("elderbrain-" + self.owner + ".tar.zst")
        self.result = {"archive": str(self.archive), "preview": {"files": 3}}
        self.repository.transfer.return_value = {"state": "completed", "preview": {"files": 3}}

    def coordinator(self):
        return PendingBackup(self.state, self.runtime, snapshots=self.snapshots,
                             repository=self.repository)

    def test_failed_upload_retains_exact_archive_checkpoint_and_pin_for_retry(self):
        self.repository.transfer.side_effect = RuntimeError("offline")
        with patch("backup_pending.create_checkpoint_backup", return_value=self.result) as create:
            result = self.coordinator().capture(self.owner)
        self.assertEqual(result["state"], "pending-upload")
        self.assertEqual(result["archive"], self.archive.name)
        self.snapshots.create.assert_called_once_with("before-shutdown", owner=self.owner,
                                                      purpose="pending-backup")
        self.snapshots.unpin.assert_not_called()
        create.assert_called_once()
        self.assertEqual(public_status(self.state)["state"], "pending-upload")
        self.assertNotIn("archive", public_status(self.state))

        self.repository.transfer.side_effect = None
        completed = self.coordinator().retry()
        self.assertEqual(completed["state"], "completed")
        transferred = self.repository.transfer.call_args
        self.assertEqual(transferred.args[0], {"archive": str(self.archive)})
        self.assertIn("deadline", transferred.kwargs)
        self.snapshots.unpin.assert_called_once_with("c" * 32, self.owner, "pending-backup")

    def test_interrupted_local_archive_stays_checkpoint_ready_and_retries(self):
        with patch("backup_pending.create_checkpoint_backup", side_effect=RuntimeError("interrupted")):
            result = self.coordinator().capture(self.owner)
        self.assertEqual(result["state"], "checkpoint-ready")
        self.snapshots.unpin.assert_not_called()
        with patch("backup_pending.create_checkpoint_backup", return_value=self.result):
            self.assertEqual(self.coordinator().retry()["state"], "completed")

    def test_retry_rejects_record_without_its_exact_validated_pin(self):
        self.snapshots.pinned_records.return_value = []
        record = {"format": 1, "id": self.owner, "checkpoint": "c" * 32,
                  "state": "checkpoint-ready", "createdAt": 123}
        self.coordinator().write(record)
        with self.assertRaisesRegex(ValueError, "matching shutdown checkpoint pin"):
            self.coordinator().retry(record)
        self.repository.transfer.assert_not_called()

    def test_uploaded_receipt_converges_if_pin_was_already_released(self):
        record = {"format": 1, "id": self.owner, "checkpoint": "c" * 32,
                  "state": "uploaded", "createdAt": 123, "uploadedAt": 124,
                  "archive": self.archive.name}
        self.coordinator().write(record)
        self.snapshots.pinned_records.return_value = []
        result = self.coordinator().retry(record)
        self.assertEqual(result["state"], "completed")
        self.snapshots.unpin.assert_not_called()
        self.repository.transfer.assert_not_called()

    def test_published_archive_is_recovered_after_record_write_interruption(self):
        self.archive.parent.mkdir()
        self.archive.write_bytes(b"published archive")
        manifest = {"format": 1, "applianceVersion": "test", "applianceIdentity": "test",
                    "createdAt": "2026-01-01T00:00:00+00:00", "containsSecrets": True,
                    "roots": ["foundry"], "entries": []}
        record = {"format": 1, "id": self.owner, "checkpoint": "c" * 32,
                  "state": "checkpoint-ready", "createdAt": 123}
        with patch("backup_pending.backup_archive.validate", return_value=manifest), \
                patch("backup_pending.create_checkpoint_backup") as create:
            self.assertEqual(self.coordinator().retry(record)["state"], "completed")
        create.assert_not_called()
        self.repository.transfer.assert_called_once()

    def test_lost_record_is_reconstructed_only_from_complete_unique_pin(self):
        with patch("backup_pending.create_checkpoint_backup", return_value=self.result):
            result = self.coordinator().retry()
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["createdAt"], 123)
        self.snapshots.unpin.assert_called_once()

        (self.state / "pending-backup" / (self.owner + ".json")).unlink()
        self.snapshots.pinned_records.return_value.append({
            "pin": {"id": "d" * 32, "owner": "e" * 32, "purpose": "pending-backup"},
            "checkpoint": {"id": "d" * 32, "reason": "before-shutdown", "createdAt": 124},
        })
        with patch("backup_pending.create_checkpoint_backup", return_value={
                "archive": str(self.archive),
                "preview": {"files": 4}}):
            recovered = self.coordinator().retry()
        self.assertEqual(recovered["id"], self.owner)
        records = list((self.state / "pending-backup").glob("*.json"))
        self.assertEqual({path.stem for path in records}, {self.owner, "e" * 32})

    def test_each_offline_shutdown_queues_a_new_pinned_generation(self):
        self.repository.transfer.side_effect = RuntimeError("offline")
        second_owner = "b" * 32
        second_archive = self.state / "backups" / ("elderbrain-" + second_owner + ".tar.zst")
        with patch("backup_pending.create_checkpoint_backup", side_effect=[
                self.result, {"archive": str(second_archive), "preview": {"files": 4}}]):
            first = self.coordinator().capture(self.owner)
            self.snapshots.create.return_value = {"id": "d" * 32}
            self.snapshots.pinned_records.return_value.append({
                "pin": {"id": "d" * 32, "owner": second_owner, "purpose": "pending-backup"},
                "checkpoint": {"id": "d" * 32, "reason": "before-shutdown", "createdAt": 124},
            })
            second = self.coordinator().capture(second_owner)
        self.assertEqual(first["state"], "pending-upload")
        self.assertEqual(second["state"], "pending-upload")
        self.assertEqual(self.snapshots.create.call_count, 2)
        self.assertEqual(public_status(self.state)["pendingCount"], 2)

    def test_shutdown_trigger_is_explicit_but_existing_pending_work_is_not_abandoned(self):
        self.assertEqual(protect(self.state, self.runtime, snapshots=self.snapshots,
                                 repository=self.repository)["state"], "local-checkpoint")
        self.snapshots.create.assert_called_once_with("before-shutdown")
        self.snapshots.reset_mock()
        BorgSettings(self.state).configure({"kind": "nfs", "host": "nas", "export": "/backup",
            "repository": "elderbrain", "onShutdown": True})
        with patch("backup_pending.create_checkpoint_backup", return_value=self.result):
            self.assertEqual(protect(self.state, self.runtime, self.owner,
                snapshots=self.snapshots, repository=self.repository)["state"], "completed")

    def test_pre_update_policy_records_failure_or_blocks_after_checkpoint(self):
        settings = {"kind": "nfs", "host": "nas", "export": "/backup",
                    "repository": "elderbrain", "beforeUpdate": True}
        BorgSettings(self.state).configure(settings)
        self.repository.backup.side_effect = RuntimeError("offline secret")
        record = {"id": self.owner, "rollbackCheckpoint": "c" * 32}
        self.assertEqual(protect_update(self.state, self.runtime, Mock(), record,
                         repository=self.repository)["state"], "failed")
        self.assertEqual(record["remoteBackup"], {"state": "failed", "failurePolicy": "continue"})

        BorgSettings(self.state).configure({**settings, "updateFailurePolicy": "block"})
        record = {"id": self.owner, "rollbackCheckpoint": "c" * 32}
        with self.assertRaisesRegex(RuntimeError, "pre-update remote backup failed"):
            protect_update(self.state, self.runtime, Mock(), record, repository=self.repository)
        self.assertEqual(record["remoteBackup"]["failurePolicy"], "block")

    def test_successful_pre_update_backup_is_recorded(self):
        BorgSettings(self.state).configure({"kind": "nfs", "host": "nas", "export": "/backup",
            "repository": "elderbrain", "beforeUpdate": True})
        self.repository.backup.return_value = {"state": "completed"}
        record = {"id": self.owner, "rollbackCheckpoint": "c" * 32}
        self.assertEqual(protect_update(self.state, self.runtime, Mock(), record,
                         repository=self.repository), {"state": "completed", "failurePolicy": "continue"})


if __name__ == "__main__":
    unittest.main()
