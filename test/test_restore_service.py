from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "appliance/lib"))
import backup_archive
from backup_service import Maintenance
from restore_service import RestoreCoordinator
from restore_transaction import RestoreTransaction


class Services:
    def __init__(self, live):
        self.live = live
        self.events = []
        self.reject_new = False
        self.stop_fails = False

    def snapshot(self):
        return {"compose": ["foundry"], "graphics": False}

    def stop(self, saved):
        self.events.append("stop")
        if self.stop_fails:
            raise RuntimeError("cannot stop writers")

    def validate(self):
        self.events.append("validate")

    def resume_restored(self, saved):
        self.events.append("resume")
        if self.reject_new and (self.live / "data").read_text() == "new":
            raise RuntimeError("restored service unhealthy")


class RestoreServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.live, self.staged = self.root / "live", self.root / "staged"
        self.live.mkdir()
        self.staged.mkdir()
        (self.live / "data").write_text("old")
        (self.staged / "data").write_text("new")
        self.services = Services(self.live)
        self.maintenance = Maintenance(self.root / "maintenance", self.services)
        self.coordinator = RestoreCoordinator(self.maintenance, {"elderbrain": self.live}, self.rollback_archive)

    def rollback_archive(self, operation):
        archive = self.root / (operation["id"] + ".tar.zst")
        self.assertEqual(self.services.events[-1], "stop")
        backup_archive.create(archive, {"elderbrain": self.live}, version="test", identity="test")
        return archive

    def test_success_has_verified_rollback_archive_and_new_data(self):
        result = self.coordinator.restore({"elderbrain": self.staged})
        self.assertEqual(result["state"], "completed")
        self.assertEqual((self.live / "data").read_text(), "new")
        with backup_archive.stage(result["rollbackArchive"], parent=self.root) as (contents, _):
            self.assertEqual((contents / "elderbrain/data").read_text(), "old")
        self.assertEqual(self.services.events, ["stop", "validate", "resume"])

    def test_persistent_alias_refresh_precedes_validation_and_resume(self):
        def refresh():
            self.assertEqual((self.live / 'data').read_text(), 'new')
            self.services.events.append('refresh')
        self.coordinator.refresh_targets = refresh
        self.coordinator.restore({'elderbrain': self.staged})
        self.assertEqual(self.services.events, ['stop', 'refresh', 'validate', 'resume'])

    def test_failed_alias_refresh_rolls_back_and_refreshes_old_tree(self):
        seen = []
        def refresh():
            value = (self.live / 'data').read_text()
            seen.append(value)
            if value == 'new':
                raise RuntimeError('mount refresh failed')
        self.coordinator.refresh_targets = refresh
        with self.assertRaisesRegex(RuntimeError, 'mount refresh failed'):
            self.coordinator.restore({'elderbrain': self.staged})
        self.assertEqual(seen, ['new', 'old'])
        self.assertEqual(self.maintenance.previous()['state'], 'rolled-back')
        self.assertEqual((self.live / 'data').read_text(), 'old')

    def test_failed_recovery_refresh_does_not_restart_writers(self):
        def refresh():
            raise RuntimeError('persistent mount unavailable')
        self.coordinator.refresh_targets = refresh
        with self.assertRaisesRegex(RuntimeError, 'persistent mount unavailable'):
            self.coordinator.restore({'elderbrain': self.staged})
        self.assertNotIn('resume', self.services.events)
        self.assertNotIn('validate', self.services.events)
        self.assertEqual(self.maintenance.previous()['state'], 'recovery-required')

    def test_failed_health_rolls_back_and_restarts_old_configuration(self):
        self.services.reject_new = True
        with self.assertRaisesRegex(RuntimeError, "unhealthy"):
            self.coordinator.restore({"elderbrain": self.staged})
        self.assertEqual((self.live / "data").read_text(), "old")
        self.assertEqual(self.maintenance.previous()["state"], "rolled-back")
        self.assertEqual(self.services.events, ["stop", "validate", "resume", "stop", "validate", "resume"])

    def test_failed_rollback_archive_never_replaces_live_data(self):
        def failure(record):
            raise OSError("disk full")
        self.coordinator.make_rollback = failure
        with self.assertRaisesRegex(OSError, "disk full"):
            self.coordinator.restore({"elderbrain": self.staged})
        self.assertEqual((self.live / "data").read_text(), "old")
        self.assertEqual(self.maintenance.previous()["state"], "rolled-back")

    def test_process_loss_after_apply_is_recovered_using_durable_transaction(self):
        original = RestoreTransaction.apply

        def crash(transaction):
            original(transaction)
            raise SystemExit("power loss")

        with patch.object(RestoreTransaction, "apply", crash):
            with self.assertRaises(SystemExit):
                self.coordinator.restore({"elderbrain": self.staged})
        self.assertEqual((self.live / "data").read_text(), "new")
        with self.assertRaisesRegex(RuntimeError, "roll back"):
            self.maintenance.recover()
        restarted = RestoreCoordinator(self.maintenance, {"elderbrain": self.live}, self.rollback_archive)
        self.assertEqual(restarted.recover()["state"], "rolled-back")
        self.assertEqual((self.live / "data").read_text(), "old")

    def test_stop_failure_blocks_mutation_and_future_maintenance(self):
        self.services.stop_fails = True
        with self.assertRaisesRegex(RuntimeError, "writers"):
            self.coordinator.restore({"elderbrain": self.staged})
        self.assertEqual((self.live / "data").read_text(), "old")
        self.assertEqual(self.maintenance.previous()["state"], "recovery-required")
        with self.assertRaisesRegex(RuntimeError, "Interrupted"):
            with self.maintenance.window("backup"):
                self.fail("backup must wait for restore recovery")


if __name__ == "__main__":
    unittest.main()
