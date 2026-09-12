"""Opt-in real Borg 1/Borgmatic test; all repository data lives in a temp directory."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "appliance/lib"))
import backup_archive
from borg_repository import BorgRepository
from backup_uploads import UploadStore


@unittest.skipUnless(os.environ.get("ELDERBRAIN_TEST_BORG_INTEGRATION"), "requires isolated Borg and Borgmatic binaries")
class BorgIntegrationTests(unittest.TestCase):
    def test_encrypted_repository_roundtrip_and_independent_recovery(self):
        with tempfile.TemporaryDirectory(prefix="elderbrain-real-borg-") as temp:
            root = Path(temp)
            runtime = root / "runtime"
            runtime.mkdir()
            (runtime / "VERSION").write_text("test-version")
            binary = Path(os.environ["ELDERBRAIN_TEST_BORG_INTEGRATION"])
            environment = {"PATH": str(binary.parent) + os.pathsep + os.environ["PATH"],
                           "BORG_CACHE_DIR": str(root / "cache"), "BORG_SECURITY_DIR": str(root / "security"),
                           "BORG_KEYS_DIR": str(root / "keys"), "XDG_STATE_HOME": str(root / "xdg-state"),
                           "XDG_CACHE_HOME": str(root / "xdg-cache"), "XDG_RUNTIME_DIR": str(root / "run")}
            (root / "run").mkdir(mode=0o700)
            repository = BorgRepository(root, runtime, identity="test-appliance", executable=binary, mountpoint=root / "nfs")
            repository.mountpoint.mkdir()
            repository.settings.configure({"kind": "nfs", "host": "unused-test-host", "export": "/unused",
                                           "repository": "repository", "passphrase": "test-recovery-passphrase"})
            # Only the NFS transport check is bypassed. All Borgmatic/Borg commands
            # execute against a real encrypted repository on the temp filesystem.
            with patch.dict(os.environ, environment), patch.object(repository, "ensure_nfs"):
                try:
                    repository.initialize()
                    source = root / "source"
                    source.mkdir()
                    (source / "secret.json").write_text('{"testSecret":"preserve-me"}')
                    (source / "secret.json").chmod(0o600)
                    archive = root / "manual.tar.zst"

                    def snapshot():
                        manifest = backup_archive.create(archive, {"elderbrain": source}, version="test-version", identity="test-appliance")
                        return {"archive": str(archive), "preview": backup_archive.preview(manifest)}

                    repository.backup(snapshot)
                    archives = repository.list_archives()
                    self.assertEqual(len(archives), 1)
                    self.assertEqual(archives[0]["applianceIdentity"], "test-appliance")
                    self.assertEqual(archives[0]["applianceVersion"], "test-version")
                    uploaded = repository.fetch_archive(archives[0]["name"])
                    uploaded_path, _ = UploadStore(root / "uploads").verify(uploaded["id"])
                    self.assertEqual(uploaded_path.read_bytes(), archive.read_bytes())
                    with backup_archive.stage(uploaded_path, parent=root) as (contents, _):
                        self.assertEqual((contents / "elderbrain/secret.json").read_text(), '{"testSecret":"preserve-me"}')
                    kit_result = repository.recovery_kit()
                    kit = json.loads(Path(kit_result["archive"]).read_text())
                    keyfile = root / "exported-key"
                    keyfile.write_text(kit["borgRepositoryKey"])
                    keyfile.chmod(0o600)
                    recovery_env = {**os.environ, "BORG_PASSPHRASE": kit["settings"]["passphrase"],
                                    "BORG_CACHE_DIR": str(root / "fresh-cache"), "BORG_SECURITY_DIR": str(root / "fresh-security")}
                    subprocess.run([str(binary.parent / "borg"), "key", "import", kit["repository"], str(keyfile)],
                                   env=recovery_env, check=True, capture_output=True, timeout=60)
                    recovered = subprocess.run([str(binary.parent / "borg"), "list", "--json", kit["repository"]],
                                               env=recovery_env, check=True, capture_output=True, text=True, timeout=60)
                    self.assertEqual(len(json.loads(recovered.stdout)["archives"]), 1)
                    denied = subprocess.run([str(binary.parent / "borg"), "list", kit["repository"]],
                                            env={**recovery_env, "BORG_PASSPHRASE": "incorrect-test-passphrase"},
                                            capture_output=True, timeout=60)
                    self.assertNotEqual(denied.returncode, 0)
                except subprocess.CalledProcessError as error:
                    # Synthetic test credentials only; include diagnostics needed
                    # to distinguish real protocol/configuration failures.
                    self.fail(f"Borg command failed: {error.cmd}: {error.stderr}")


if __name__ == "__main__":
    unittest.main()
