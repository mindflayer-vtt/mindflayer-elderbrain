import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from release_baseline_seed import finalize, install_metadata
from release_policy import ReleasePolicy


class BaselineSeedTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.state = self.root / "var/lib/mindflayer-elderbrain"
        self.runtime = self.root / "opt/mindflayer-elderbrain"
        self.etc = self.root / "etc/elderbrain"
        self.state.mkdir(parents=True)
        self.runtime.mkdir(parents=True)
        self.etc.mkdir(parents=True)
        (self.runtime / "VERSION").write_text("1.0.0\n")
        (self.runtime / "baseline-stack.service").write_text("fixture")
        core = {"format": 1, "version": "1.0.0", "releaseSequence": 2,
                "sourceCommit": "a" * 40, "sourceTree": "b" * 40,
                "inputMode": "tracked-commit"}
        encoded = json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
        self.metadata = {**core, "sourceIdentity": hashlib.sha256(encoded).hexdigest()}
        self.metadata_path = self.etc / "install-baseline.json"
        self.metadata_path.write_text(json.dumps(self.metadata, sort_keys=True) + "\n")
        self.metadata_path.chmod(0o644)
        self.prepared = self.state / "prepared"
        self.prepare = self.enterContext(patch("release_baseline_seed.prepare",
                                               return_value={"directory": str(self.prepared)}))
        self.services = self.enterContext(patch("release_baseline_seed.UpdateServices"))
        self.maintenance = self.enterContext(patch("release_baseline_seed.Maintenance"))
        self.migration = self.enterContext(patch("release_baseline_seed.Migration")).return_value
        self.migration.install.return_value = {"state": "completed"}
        self.generation = self.enterContext(patch("release_baseline_seed.active_generation",
            return_value={"bundle": "c" * 64, "recoveryApi": 1}))
        self.active = self.enterContext(patch("release_baseline_seed.verify_active"))

    def test_first_boot_installs_immutable_compose_and_release_sequence_once(self):
        result = finalize(host_root=self.root)
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["releaseSequence"], 2)
        self.assertEqual(ReleasePolicy(self.state).current()["highestSequence"], 2)
        self.migration.install.assert_called_once()
        self.assertIs(self.prepare.call_args.kwargs["run"], subprocess.run)
        self.assertIs(self.migration.install.call_args.kwargs["run"], subprocess.run)
        prerequisite = self.migration.install.call_args.kwargs["require_bootstrap"]
        prerequisite()
        self.active.assert_called_once_with("c" * 64, 1, host_root=self.root)

        self.migration.install.reset_mock()
        self.assertEqual(finalize(host_root=self.root), result)
        self.migration.install.assert_not_called()

    def test_preserve_reinstall_explicitly_reestablishes_its_older_iso_baseline(self):
        ReleasePolicy(self.state).commit({"releaseSequence": 9, "version": "9.0.0",
                                          "manifestSha256": "d" * 64})
        finalize(host_root=self.root)
        self.assertEqual(ReleasePolicy(self.state).current()["highestSequence"], 2)

    def test_completed_baseline_allows_a_later_accepted_online_release(self):
        receipt = finalize(host_root=self.root)
        ReleasePolicy(self.state).commit({"releaseSequence": 3, "version": "2.0.0",
                                          "manifestSha256": "d" * 64})
        (self.runtime / "VERSION").write_text("1.9.0\n")
        self.migration.install.reset_mock()
        self.assertEqual(finalize(host_root=self.root), receipt)
        self.migration.install.assert_not_called()

    def test_failed_migration_does_not_change_policy_or_publish_completion(self):
        self.migration.install.side_effect = RuntimeError("migration failed")
        with self.assertRaisesRegex(RuntimeError, "migration failed"):
            finalize(host_root=self.root)
        self.assertEqual(ReleasePolicy(self.state).current(), {"highestSequence": 0})
        self.assertFalse((self.etc / "install-baseline-complete.json").exists())

    def test_metadata_identity_and_permissions_fail_closed(self):
        value = json.loads(self.metadata_path.read_text())
        value["releaseSequence"] = 3
        self.metadata_path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "source identity"):
            install_metadata(self.metadata_path)
        self.metadata_path.chmod(0o600)
        with self.assertRaisesRegex(ValueError, "root-owned"):
            install_metadata(self.metadata_path)


if __name__ == "__main__":
    unittest.main()
