from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "appliance/lib"))
from borg_repository import BorgRepository
from borg_service import activate_schedule, configure, execute


class BorgServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = BorgRepository(self.root, self.root / "runtime", identity="test")
        self.settings = {"kind": "nfs", "host": "nas", "export": "/backup", "repository": "elderbrain", "schedule": "02:30"}
        self.units = self.root / "units"
        self.units.mkdir()

    def test_enable_writes_timer_and_starts_it_without_repository_side_effects(self):
        with patch.object(self.repo, "run") as run:
            result = configure(self.repo, {**self.settings, "enabled": True}, unit_directory=self.units)
            self.assertNotIn("passphrase", result)
            self.assertIn("OnCalendar=*-*-* 02:30:00", (self.units / "elderbrain-backup.timer").read_text())
            self.assertEqual([call.args[0] for call in run.call_args_list], [
                ["systemctl", "daemon-reload"], ["systemctl", "enable", "elderbrain-backup.timer"],
                ["systemctl", "restart", "elderbrain-backup.timer"]])

    def test_disabled_and_unconfigured_schedules_stop_existing_timer(self):
        with patch.object(self.repo, "run") as run:
            self.assertEqual(activate_schedule(self.repo, unit_directory=self.units)["state"], "unconfigured")
            self.assertEqual(run.call_args.args[0], ["systemctl", "disable", "--now", "elderbrain-backup.timer"])
            configure(self.repo, self.settings, unit_directory=self.units)
            self.assertEqual(run.call_args.args[0], ["systemctl", "disable", "--now", "elderbrain-backup.timer"])

    def test_connection_test_returns_archives_and_does_not_initialize(self):
        with patch.object(self.repo, "list_archives", return_value=[{"name": "elderbrain-test"}]), patch.object(self.repo, "initialize") as initialize:
            self.assertEqual(execute("test", self.repo), {"state": "connected", "archives": [{"name": "elderbrain-test"}]})
            initialize.assert_not_called()


if __name__ == "__main__":
    unittest.main()
