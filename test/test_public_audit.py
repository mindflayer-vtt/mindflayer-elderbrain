from pathlib import Path
import subprocess
import tempfile
import unittest

from release.public_audit_paths import prohibited


ROOT = Path(__file__).resolve().parents[1]


class PublicAuditTests(unittest.TestCase):
    def test_secret_artifact_paths_are_rejected_without_blocking_public_keys(self):
        rejected = prohibited({
            "config/private/smtp.json", "old/recovery-kit.json", "backup.tar.zst",
            "root/.ssh/id_ed25519", "keys/appliance-private.pem",
            "config/releases/appliance-release-public.pem",
            "config/defaults/firmware-signing-public.pem",
        })
        self.assertEqual(rejected, [
            "backup.tar.zst", "config/private/smtp.json", "keys/appliance-private.pem",
            "old/recovery-kit.json", "root/.ssh/id_ed25519",
        ])

    def test_deleted_historical_paths_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repository, check=True)
            subprocess.run(["git", "config", "user.name", "Audit Fixture"], cwd=repository, check=True)
            subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=repository, check=True)
            private = repository / "config/private"
            private.mkdir(parents=True)
            (private / "smtp.json").write_text("fixture only")
            subprocess.run(["git", "add", "."], cwd=repository, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repository, check=True)
            (private / "smtp.json").unlink()
            subprocess.run(["git", "commit", "-qam", "remove fixture"], cwd=repository, check=True)
            process = subprocess.run([
                "python3", str(ROOT / "release/public_audit_paths.py"), str(repository),
            ], text=True, capture_output=True)
            self.assertEqual(process.returncode, 1)
            self.assertIn("config/private/smtp.json", process.stdout)
            self.assertNotIn("fixture only", process.stdout)

    def test_audit_tool_and_checksum_are_pinned_and_output_is_redacted(self):
        script = (ROOT / "release/public-audit.sh").read_text()
        self.assertIn("version=8.30.1", script)
        self.assertRegex(script, r"archive_sha256=[0-9a-f]{64}")
        self.assertIn("--log-opts=--all", script)
        self.assertIn("--redact", script)
        self.assertIn("git clone --quiet --mirror", script)
        self.assertIn("git -C \"$root\" archive --format=tar HEAD", script)


if __name__ == "__main__":
    unittest.main()
