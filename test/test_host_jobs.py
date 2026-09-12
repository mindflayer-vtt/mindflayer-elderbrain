import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "appliance/lib"))
from host_jobs import JobStore, worker
from backup_service import save_record


class JobTests(unittest.TestCase):
    def test_network_restore_admission_requires_consent_and_digest(self):
        valid = {'checkpoint': 'b' * 32, 'interface': 'ens3', 'confirmationDigest': 'a' * 64,
                 'confirmRestore': True, 'confirmDowntime': True}
        for changes in ({'confirmRestore': False}, {'confirmDowntime': False}, {'checkpoint': '../data'},
                        {'interface': 'ens3;reboot'}, {'confirmationDigest': 'token'}, {'token': 'private'}):
            with self.assertRaises(ValueError):
                self.store.submit('network-snapshot-restore', {**valid, **changes})
        self.assertEqual(self.store.list(), [])

    def test_network_restore_worker_returns_only_transaction_status(self):
        fd = self.queued()
        path = self.store.path(self.identity)
        record = json.loads(path.read_text())
        selected = {'checkpoint': 'b' * 32, 'interface': 'ens3', 'confirmationDigest': 'a' * 64,
                    'confirmRestore': True, 'confirmDowntime': True}
        record.update(kind='network-snapshot-restore', request=selected)
        save_record(path, record)
        with patch('network_checkpoint_restore.coordinator') as coordinator:
            coordinator.return_value.start.return_value = {'id': 'c' * 32, 'phase': 'staged',
                'deadline': 1234, 'interface': 'ens3', 'token': 'never-expose', 'files': 'private'}
            worker(self.store.directory, self.identity, fd)
            coordinator.return_value.start.assert_called_once_with('b' * 32, 'ens3', confirmation_digest='a' * 64)
        saved = self.store.read(self.identity)
        self.assertEqual(saved['state'], 'completed')
        self.assertEqual(set(saved['result']), {'id', 'phase', 'deadline', 'interface'})
        self.assertNotIn('never-expose', json.dumps(saved))

    def test_worker_launch_uses_independent_scope_and_inherited_lock(self):
        with patch('host_jobs.subprocess.Popen', return_value=SimpleNamespace(wait=lambda: None)) as launch:
            record = self.store.submit('snapshot-create')
        args = launch.call_args.args[0]
        self.assertEqual(args[:4], ['systemd-run', '--scope', '--quiet', '--collect'])
        self.assertIn('--unit=elderbrain-job-' + record['id'], args)
        self.assertIn('--expand-environment=no', args)
        self.assertTrue(launch.call_args.kwargs['start_new_session'])
        self.assertEqual(len(launch.call_args.kwargs['pass_fds']), 1)

    def test_checkpoint_restore_admission_rejects_unsafe_or_unconfirmed_selection(self):
        valid = {'checkpoint': 'b' * 32, 'components': ['preferences'], 'confirmRestore': True}
        for changes in ({'confirmRestore': False}, {'checkpoint': '../disk'},
                        {'components': ['foundry/worlds']}, {'components': ['network']},
                        {'components': ['preferences', 'preferences']}, {'secret': 'unexpected'}):
            with self.assertRaises(ValueError):
                self.store.submit('snapshot-restore', {**valid, **changes})
        self.assertEqual(self.store.list(), [])

    def test_checkpoint_restore_worker_passes_fixed_arguments_and_hides_journal(self):
        fd = self.queued()
        path = self.store.path(self.identity)
        record = json.loads(path.read_text())
        record.update(kind='snapshot-restore', request={'checkpoint': 'b' * 32,
                      'components': ['preferences'], 'confirmRestore': True})
        save_record(path, record)
        def execute(args, **kwargs):
            self.assertEqual(args[1:], ['snapshot-restore', '--checkpoint', 'b' * 32,
                                       '--confirm-restore', '--component', 'preferences'])
            kwargs['stdout'].write(json.dumps({'state': 'completed', 'rollbackArchive': '/private/archive'}).encode())
            return SimpleNamespace(returncode=0)
        with patch('host_jobs.subprocess.run', side_effect=execute):
            worker(self.store.directory, self.identity, fd)
        result = self.store.read(self.identity)
        self.assertEqual(result['result'], {'state': 'completed'})
        self.assertNotIn('/private/archive', json.dumps(result))

    def test_keypad_flash_refuses_interrupted_selective_restore(self):
        from backup_service import Maintenance
        root = Path(self.temp.name)
        self.store = JobStore(root / 'jobs')
        fd = self.queued()
        path = self.store.path(self.identity)
        record = json.loads(path.read_text())
        record.update(kind='keypad-install', request={}, revision=1)
        save_record(path, record)
        save_record(path.with_suffix('.settings'), {'revision': 1})
        maintenance = Maintenance(root / 'maintenance', None)
        save_record(maintenance.journal, {'operation': 'restore', 'state': 'staging-restore'})
        with patch('installation_job.run_installation') as install:
            worker(self.store.directory, self.identity, fd)
        install.assert_not_called()
        self.assertEqual(self.store.read(self.identity)['state'], 'failed')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = JobStore(self.temp.name)
        self.identity = "a" * 32

    def queued(self):
        path = self.store.path(self.identity)
        fd = os.open(path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        save_record(path, {"id": self.identity, "kind": "backup", "state": "queued", "createdAt": 1})
        return fd

    def test_checkpoint_worker_exposes_only_public_metadata(self):
        fd = self.queued()
        path = self.store.path(self.identity)
        record = json.loads(path.read_text())
        record['kind'] = 'snapshot-create'
        save_record(path, record)
        def execute(args, **kwargs):
            self.assertEqual(args[-1], 'snapshot-create')
            kwargs['stdout'].write(json.dumps({'state': 'completed', 'checkpoint': {
                'version': 1, 'id': 'b' * 32, 'createdAt': 1, 'reason': 'manual',
                'private': 'must-not-expose'}}).encode())
            return SimpleNamespace(returncode=0)
        with patch('host_jobs.subprocess.run', side_effect=execute):
            worker(self.store.directory, self.identity, fd)
        result = self.store.read(self.identity)
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['result']['checkpoint']['id'], 'b' * 32)
        self.assertNotIn('must-not-expose', json.dumps(result))

    def test_installation_admission_snapshots_private_settings_and_rejects_stale_revision(self):
        root = Path(self.temp.name)
        self.store = JobStore(root / "jobs")
        settings = {"revision": 3, "ssid": "Table", "psk": "private-wifi-password", "serverHost": "table.local", "serverPort": 10443}
        settings_path = root / "elderbrain/secrets/keypad-settings.json"
        settings_path.parent.mkdir(parents=True)
        save_record(settings_path, settings)
        request = {"usbId": "b" * 32, "version": "1.2.3", "revision": 3, "adopt": False, "unexpectedSecret": "must-not-publish"}
        with patch("host_jobs.subprocess.Popen", return_value=SimpleNamespace(wait=lambda: None)):
            result = self.store.submit("keypad-install", request)
        self.assertNotIn(settings["psk"], json.dumps(result))
        self.assertNotIn("must-not-publish", json.dumps(result))
        snapshot = self.store.path(result["id"]).with_suffix(".settings")
        self.assertEqual(json.loads(snapshot.read_text()), settings)
        self.assertEqual(snapshot.stat().st_mode & 0o777, 0o600)
        settings["revision"] = 4
        save_record(settings_path, settings)
        with self.assertRaisesRegex(ValueError, "changed"):
            self.store.submit("keypad-install", request)
        self.assertEqual(json.loads(snapshot.read_text())["revision"], 3)

    def test_installation_worker_publishes_progress_and_result_without_private_settings(self):
        from backup_service import Maintenance
        root = Path(self.temp.name)
        self.store = JobStore(root / "jobs")
        fd = self.queued()
        path = self.store.path(self.identity)
        record = json.loads(path.read_text())
        record.update(kind="keypad-install", request={"usbId": "b" * 32, "version": "1.2.3", "adopt": False}, revision=3)
        save_record(path, record)
        save_record(path.with_suffix(".settings"), {"revision": 3, "psk": "private-wifi-password"})
        def install(directory, request, settings, backend, progress):
            self.assertEqual(directory, root / "keypad-installations" / self.identity)
            self.assertEqual(settings["psk"], "private-wifi-password")
            with self.assertRaisesRegex(RuntimeError, "maintenance"):
                with Maintenance(root / "maintenance", None).locked():
                    pass
            progress({"stage": "verify-online"})
            self.assertEqual(self.store.read(self.identity)["stage"], "verify-online")
            return {"state": "verified", "deviceId": "keypad", "revision": 3}
        with patch("installation_job.run_installation", side_effect=install), patch("installation_backend.InstallationBackend") as backend:
            worker(self.store.directory, self.identity, fd)
            self.assertEqual(len(backend.call_args.args[2]), 1)
        result = self.store.read(self.identity)
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["result"]["deviceId"], "keypad")
        self.assertNotIn("private-wifi-password", json.dumps(result))

    def test_encrypted_preview_validates_then_publishes_plaintext_without_secret(self):
        from backup_archive import create
        from backup_crypto import transform
        from backup_uploads import UploadStore
        root = Path(self.temp.name)
        source = root / "source"
        source.mkdir()
        (source / "settings").write_text("test configuration")
        archive = root / "input.tar.zst"
        create(archive, {"elderbrain": source}, version="test", identity="test-device")
        encrypted = root / "input.gpg"
        password = "test-only-decryption-password"
        transform(archive, encrypted, password)
        # Isolate the host upload directory inside this test's temporary root.
        self.store = JobStore(root / "jobs")
        uploads = UploadStore(root / "uploads")
        with encrypted.open("rb") as data:
            uploaded = uploads.receive(data, encrypted.stat().st_size)
        for supplied, expected in (("wrong-test-password", "failed"), (password, "completed")):
            with self.subTest(expected=expected):
                self.identity = ("b" if expected == "failed" else "c") * 32
                fd = self.queued()
                record = self.store.read(self.identity)
                record.update(kind="restore-preview-encrypted", uploadId=uploaded["id"])
                save_record(self.store.path(self.identity), record)
                secret = os.memfd_create("test-secret", os.MFD_CLOEXEC)
                os.write(secret, (supplied + "\n").encode())
                os.lseek(secret, 0, os.SEEK_SET)
                worker(self.store.directory, self.identity, fd, secret_fd=secret)
                result = self.store.read(self.identity)
                self.assertEqual(result["state"], expected)
                self.assertNotIn(supplied, json.dumps(result))
                self.assertFalse(list(uploads.directory.glob("elderbrain-decrypted-*")))
                if expected == "completed":
                    plaintext, _ = uploads.verify(result["uploadId"], result["result"]["sha256"])
                    self.assertEqual(plaintext.read_bytes(), archive.read_bytes())
                    self.assertEqual(result["result"]["preview"]["applianceIdentity"], "test-device")
                else:
                    self.assertEqual(len(list(uploads.directory.glob("*.tar.zst"))), 1)

    def test_lock_is_authoritative_across_store_restart(self):
        fd = self.queued()
        try:
            self.assertEqual(JobStore(self.temp.name).read(self.identity)["state"], "queued")
            with self.assertRaisesRegex(RuntimeError, "running"):
                self.store.submit("backup")
        finally:
            os.close(fd)
        self.assertEqual(JobStore(self.temp.name).read(self.identity)["state"], "interrupted")

    def test_success_persists_result_and_never_returns_raw_stderr(self):
        fd = self.queued()

        def run(args, **kwargs):
            self.assertEqual(args, ["/test/elderbrain", "backup"])
            kwargs["stdout"].write(json.dumps({"archive": "/private/backup.tar.zst", "preview": {"files": 4}}).encode())
            kwargs["stderr"].write(b"sensitive diagnostics")
            return SimpleNamespace(returncode=0)

        with patch("host_jobs.subprocess.run", side_effect=run):
            worker(self.temp.name, self.identity, fd, executable="/test/elderbrain")
        result = self.store.read(self.identity)
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["result"]["preview"]["files"], 4)
        self.assertNotIn("sensitive", json.dumps(result))
        self.assertEqual(self.store.path(self.identity).with_suffix(".stderr").stat().st_mode & 0o777, 0o600)

    def test_failed_command_only_exposes_generic_error(self):
        fd = self.queued()
        with patch("host_jobs.subprocess.run", return_value=SimpleNamespace(returncode=1)):
            worker(self.temp.name, self.identity, fd)
        self.assertEqual(self.store.read(self.identity)["state"], "failed")
        self.assertNotIn("result", self.store.read(self.identity))

    def test_unknown_kind_and_traversal_are_rejected(self):
        with self.assertRaises(ValueError):
            self.store.submit("shell")
        with self.assertRaises(ValueError):
            self.store.read("../../secret")

    def test_spawn_failure_is_durable(self):
        with patch("host_jobs.subprocess.Popen", side_effect=OSError("spawn failed")):
            with self.assertRaises(OSError):
                self.store.submit("backup")
        self.assertEqual(self.store.list()[0]["state"], "failed")

    def test_encryption_secret_is_inherited_in_memory_not_job_record_or_arguments(self):
        password = "test-memory-only-passphrase"
        def spawn(arguments, **options):
            secret_fd = options["pass_fds"][1]
            self.assertEqual(os.read(secret_fd, 8192).decode(), password + "\n")
            self.assertNotIn(password, " ".join(arguments))
            return SimpleNamespace(wait=lambda: 0)
        with patch("host_jobs.subprocess.Popen", side_effect=spawn):
            record = self.store.submit("backup-encrypted", passphrase=password)
        self.assertNotIn(password, json.dumps(record))
        self.assertNotIn(password, self.store.path(record["id"]).read_text())
        self.assertFalse(any("secret" in path.name for path in self.store.directory.iterdir()))

    def test_encryption_worker_passes_descriptor_and_closes_it(self):
        fd = self.queued()
        path = self.store.path(self.identity)
        record = json.loads(path.read_text())
        record["kind"] = "backup-encrypted"
        save_record(path, record)
        secret_fd = os.memfd_create("test-secret")
        os.write(secret_fd, b"test-encryption-password\n")
        os.lseek(secret_fd, 0, os.SEEK_SET)
        def run(arguments, **options):
            self.assertEqual(arguments[-2:], ["--passphrase-fd", str(secret_fd)])
            self.assertIn(secret_fd, options["pass_fds"])
            options["stdout"].write(json.dumps({"archive": "/private/archive.tar.zst.gpg", "preview": {}}).encode())
            return SimpleNamespace(returncode=0)
        with patch("host_jobs.subprocess.run", side_effect=run):
            worker(self.temp.name, self.identity, fd, secret_fd=secret_fd)
        self.assertTrue(self.store.read(self.identity)["result"]["encrypted"])
        with self.assertRaises(OSError):
            os.fstat(secret_fd)

    def test_download_only_opens_completed_regular_backup_artifact(self):
        root = Path(self.temp.name)
        store = JobStore(root / "jobs")
        (root / "backups").mkdir()
        archive = root / "backups" / ("elderbrain-" + self.identity + ".tar.zst")
        archive.write_bytes(b"archive-bytes")
        record = {"id": self.identity, "kind": "backup", "state": "completed", "createdAt": 1,
                  "result": {"archive": str(archive)}}
        save_record(store.path(self.identity), record)
        data, size = store.open_backup(self.identity)
        with data:
            self.assertEqual(data.read(), b"archive-bytes")
            self.assertEqual(size, 13)
        archive.unlink()
        archive.symlink_to(root / "secret")
        with self.assertRaises(OSError):
            store.open_backup(self.identity)
        record["result"]["archive"] = str(root / "secret")
        save_record(store.path(self.identity), record)
        with self.assertRaises(ValueError):
            store.open_backup(self.identity)


if __name__ == "__main__":
    unittest.main()
