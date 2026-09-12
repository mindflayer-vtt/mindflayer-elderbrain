import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "appliance/lib"))
from restore_transaction import RestoreTransaction


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.live = self.root / "live"
        self.source = self.root / "source"
        self.live.mkdir()
        self.source.mkdir()
        (self.live / "old-only").write_text("old state")
        (self.source / "secret").write_text("new state")
        (self.source / "secret").chmod(0o600)
        self.journal = self.root / "restore.json"
        self.transaction = RestoreTransaction(self.journal, {"data": self.live})

    def test_apply_is_exact_and_rollback_restores_old_tree(self):
        self.transaction.prepare({"data": self.source})
        self.assertTrue((self.live / "old-only").exists())
        self.transaction.apply()
        self.assertFalse((self.live / "old-only").exists())
        self.assertEqual((self.live / "secret").read_text(), "new state")
        self.assertEqual((self.live / "secret").stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.live / "secret").stat().st_uid, os.getuid())
        restarted = RestoreTransaction(self.journal, {"data": self.live})
        restarted.rollback()
        self.assertEqual((self.live / "old-only").read_text(), "old state")
        self.assertFalse((self.live / "secret").exists())
        restarted.rollback()

    def test_commit_retains_private_previous_tree(self):
        self.transaction.prepare({"data": self.source})
        self.transaction.apply()
        record = self.transaction.commit()
        retained = self.transaction.location(record, "data")
        self.assertEqual(retained.stat().st_mode & 0o777, 0o700)
        self.assertEqual((retained / "previous/old-only").read_text(), "old state")
        with self.assertRaisesRegex(ValueError, "Committed"):
            self.transaction.rollback()

    def test_interruption_between_renames_recovers_without_losing_old_state(self):
        self.transaction.prepare({"data": self.source})
        rename = os.rename

        def interrupted(source, target):
            if Path(source).name == "incoming":
                raise OSError("simulated power loss")
            return rename(source, target)

        with patch("restore_transaction.os.rename", side_effect=interrupted):
            with self.assertRaisesRegex(OSError, "power loss"):
                self.transaction.apply()
        self.assertFalse(self.live.exists())
        RestoreTransaction(self.journal, {"data": self.live}).rollback()
        self.assertEqual((self.live / "old-only").read_text(), "old state")

    def test_new_target_is_removed_by_recoverable_rename_on_rollback(self):
        target = self.root / "new-target"
        transaction = RestoreTransaction(self.journal, {"data": target})
        transaction.prepare({"data": self.source})
        transaction.apply()
        record = transaction.rollback()
        self.assertFalse(target.exists())
        self.assertEqual((transaction.location(record, "data") / "rejected/secret").read_text(), "new state")

    def test_mapping_change_and_overlapping_targets_are_rejected(self):
        self.transaction.prepare({"data": self.source})
        with self.assertRaisesRegex(ValueError, "mapping changed"):
            RestoreTransaction(self.journal, {"data": self.root / "other"}).rollback()
        with self.assertRaisesRegex(ValueError, "overlap"):
            RestoreTransaction(self.journal, {"one": self.live, "two": self.live / "nested"})

    def test_partial_multi_target_install_rolls_back_all_targets(self):
        second = self.root / "second"
        second.write_text("old second")
        transaction = RestoreTransaction(self.journal, {"one": self.live, "two": second})
        transaction.prepare({"one": self.source, "two": self.source / "secret"})
        rename = os.rename

        def interrupted(source, target):
            if Path(target) == second:
                raise OSError("interrupted second target")
            return rename(source, target)

        with patch("restore_transaction.os.rename", side_effect=interrupted):
            with self.assertRaises(OSError):
                transaction.apply()
        transaction.rollback()
        self.assertTrue((self.live / "old-only").exists())
        self.assertEqual(second.read_text(), "old second")


if __name__ == "__main__":
    unittest.main()
