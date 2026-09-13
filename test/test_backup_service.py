import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "appliance/lib"))
from backup_service import Maintenance, HostServices, create_backup
import backup_archive


class Services:
    def __init__(self):
        self.events = []
        self.fail_stop = False
        self.fail_resume = False

    def snapshot(self):
        self.events.append("snapshot")
        return {"compose": ["foundry"], "graphics": False}

    def stop(self, saved):
        self.events.append(("stop", saved))
        if self.fail_stop:
            raise RuntimeError("stop failure")

    def resume(self, saved):
        self.events.append(("resume", saved))
        if self.fail_resume:
            raise RuntimeError("resume failure")

    def validate(self):
        self.events.append("validate")

    def resume_restored(self, saved):
        self.resume(saved)


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.services = Services()
        self.maintenance = Maintenance(self.temp.name, self.services)

    def test_success_preserves_saved_service_set_and_journals(self):
        with self.maintenance.window("backup"):
            self.assertEqual(self.maintenance.previous()["state"], "working")
        self.assertEqual(self.maintenance.previous()["state"], "completed")
        self.assertEqual(self.services.events, ["snapshot", ("stop", {"compose": ["foundry"], "graphics": False}),
                                                ("resume", {"compose": ["foundry"], "graphics": False})])
        self.assertEqual(self.maintenance.journal.stat().st_mode & 0o777, 0o600)

    def test_work_failure_still_resumes_services(self):
        with self.assertRaisesRegex(RuntimeError, "archive failure"):
            with self.maintenance.window("backup"):
                raise RuntimeError("archive failure")
        self.assertEqual(self.services.events[-1][0], "resume")
        self.assertEqual(self.maintenance.previous()["state"], "failed")

    def test_partial_stop_failure_still_resumes_original_services(self):
        self.services.fail_stop = True
        with self.assertRaisesRegex(RuntimeError, "stop failure"):
            with self.maintenance.window("backup"):
                self.fail("should not start backup")
        self.assertEqual(self.services.events[-1][0], "resume")

    def test_resume_failure_requires_explicit_recovery(self):
        self.services.fail_resume = True
        with self.assertRaisesRegex(RuntimeError, "resume failure"):
            with self.maintenance.window("backup"):
                pass
        self.assertEqual(self.maintenance.previous()["state"], "recovery-required")
        with self.assertRaisesRegex(RuntimeError, "Interrupted"):
            with self.maintenance.window("backup"):
                self.fail("should remain blocked")
        self.services.fail_resume = False
        self.assertEqual(self.maintenance.recover()["state"], "recovered")
        with self.maintenance.window("backup"):
            pass

    def test_process_restart_recovers_durable_interrupted_state(self):
        self.maintenance.journal.write_text(json.dumps({"state": "working", "services": {"compose": ["foundry"], "graphics": False}}))
        restarted = Maintenance(self.temp.name, self.services)
        self.assertEqual(restarted.recover()["state"], "recovered")
        self.assertEqual(self.services.events[0][0], "resume")

    def test_exclusive_lock_blocks_competing_operation(self):
        with self.maintenance.locked():
            with self.assertRaisesRegex(RuntimeError, "running"):
                with Maintenance(self.temp.name, self.services).window("backup"):
                    self.fail("concurrent backup was allowed")

    def test_host_stop_uses_saved_project_not_restored_compose(self):
        host = HostServices(Path("/opt/test-runtime"))
        with patch.object(host, "run", side_effect=[SimpleNamespace(stdout="abc123\n"), SimpleNamespace(stdout="")]) as run:
            host.stop({"compose": ["foundry"], "graphics": False, "project": "mindflayer-elderbrain"})
            self.assertEqual(run.call_args_list[0].args[0], ["docker", "ps", "-q", "--filter", "label=com.docker.compose.project=mindflayer-elderbrain"])
            self.assertEqual(run.call_args_list[1].args[0], ["docker", "stop", "--time", "60", "abc123"])

    def test_coordinator_backs_up_all_configured_sources_with_secrets(self):
        # This fixture runs unprivileged locally. Root-owned policy metadata is
        # exercised separately by the same test running as root in the VM.
        from local_snapshots import Snapshots, validate_retention
        import json
        import os
        if os.geteuid() != 0:
            def read_fixture_policy(snapshot):
                file = snapshot.root / '.retention'
                return validate_retention(json.loads(file.read_text())) if file.exists() else {'enabled': False, 'keep': 10}
            mocked = patch.object(Snapshots, 'read_retention', read_fixture_policy)
            mocked.start()
            self.addCleanup(mocked.stop)
        root = Path(self.temp.name)
        state, runtime, host = root / "state", root / "runtime", root / "host"
        runtime.mkdir()
        for name in ("foundry", "elderbrain", "mindflayer", "firmware", "traefik", "browser"):
            directory = state / name
            directory.mkdir(parents=True)
            (directory / "user-data").write_text("data-for-" + name)
        from admin_tls import openssl
        ca, tls = state / 'host/admin-ca', state / 'traefik/tls'
        ca.mkdir(parents=True, mode=0o700); tls.mkdir()
        (state / 'traefik/admin-tls.yaml').write_text(
            'tls:\n  stores:\n    default:\n      defaultCertificate:\n'
            '        certFile: /etc/traefik/dynamic/tls/admin.crt\n'
            '        keyFile: /etc/traefik/dynamic/tls/admin.key\n')
        openssl(['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', ca / 'ca.key',
                 '-out', ca / 'ca.crt', '-days', '1', '-subj', '/CN=backup-test-CA',
                 '-addext', 'basicConstraints=critical,CA:TRUE',
                 '-addext', 'keyUsage=critical,keyCertSign,cRLSign'])
        openssl(['req', '-new', '-newkey', 'rsa:2048', '-nodes', '-keyout', tls / 'admin.key',
                 '-out', tls / 'request.pem', '-subj', '/CN=elderbrain',
                 '-addext', 'subjectAltName=DNS:elderbrain,IP:127.0.0.1'])
        openssl(['x509', '-req', '-in', tls / 'request.pem', '-CA', ca / 'ca.crt',
                 '-CAkey', ca / 'ca.key', '-set_serial', '1', '-days', '1',
                 '-copy_extensions', 'copy', '-out', tls / 'admin.crt'])
        (tls / 'ca.crt').write_bytes((ca / 'ca.crt').read_bytes())
        (state / "elderbrain/secrets").mkdir(mode=0o700)
        (state / "elderbrain/secrets/admin.json").write_text('{"passwordHash":"test"}')
        journals = state / "keypad-installations"
        journals.mkdir(mode=0o700)
        journal = journals / "private-plan.json"
        journal.write_text('{"credential":"saved-device-secret"}')
        journal.chmod(0o600)
        for name in ("appliance.env", "compose.yaml", "VERSION", "sway.conf"):
            (runtime / name).write_text("test")
        for name in ("etc/systemd/system", "etc/ssh", "root/.ssh", "home/elderbrain-installer/.ssh"):
            (host / name).mkdir(parents=True)
        for name in ("elderbrain-stack.service", "elderbrain-baseline.service",
                     "elderbrain-management.service",
                     "elderbrain-graphics.service", "elderbrain-backup.service",
                     "elderbrain-backup-retry.service"):
            (host / "etc/systemd/system" / name).write_text("unit")
        (host / "etc/machine-id").write_text("test-appliance")
        (host / "root/.ssh/authorized_keys").write_text("test-public-key")
        (state / 'snapshots').mkdir(mode=0o700)
        policy = state / 'snapshots/.retention'
        policy.write_text('{"enabled":true,"keep":3}')
        policy.chmod(0o600)
        result = create_backup(state / "backups", state, runtime, self.maintenance, host_root=host)
        self.assertEqual(set(result["preview"]["roots"]), backup_archive.ROOTS)
        self.assertEqual(self.maintenance.previous()["state"], "completed")
        with backup_archive.stage(result["archive"], parent=root) as (contents, manifest):
            self.assertEqual((contents / "elderbrain/secrets/admin.json").read_text(), '{"passwordHash":"test"}')
            self.assertEqual((contents / "ssh-root/authorized_keys").read_text(), "test-public-key")
            self.assertTrue((contents / 'admin-ca/ca.key').is_file())
            self.assertFalse((contents / 'traefik/tls/ca.key').exists())
            self.assertEqual((contents / 'admin-ca/ca.crt').read_bytes(),
                             (contents / 'traefik/tls/ca.crt').read_bytes())
            self.assertEqual(manifest["applianceIdentity"], "test-appliance")
            self.assertEqual((contents / "keypad-installations/private-plan.json").read_text(), '{"credential":"saved-device-secret"}')
            self.assertEqual(json.loads((contents / 'service-config/checkpoint-retention.json').read_text()), {'enabled': True, 'keep': 3})
            legacy = root / "legacy.tar.zst"
            (contents / 'service-config/checkpoint-retention.json').unlink()
            backup_archive.create(legacy, {name: contents / name for name in manifest["roots"] if name != "keypad-installations"}, version="test", identity="test-appliance")
            # A valid archive checksum is not sufficient: settings must still
            # pass semantic validation before any live services are stopped.
            (contents / 'service-config/checkpoint-retention.json').write_text('{"enabled":true,"keep":0}')
            invalid_policy = root / 'invalid-policy.tar.zst'
            backup_archive.create(invalid_policy, {name: contents / name for name in manifest['roots']},
                                  version='test', identity='test-appliance')
            (contents / 'traefik/tls/ca.key').write_text('must-never-be-served')
            invalid_ca = root / 'invalid-ca.tar.zst'
            backup_archive.create(invalid_ca, {name: contents / name for name in manifest['roots']},
                                  version='test', identity='test-appliance')
            (contents / 'traefik/tls/ca.key').unlink()
        from restore_service import restore_host, recover_host
        (state / "elderbrain/secrets/admin.json").write_text("changed-secret")
        (runtime / "sway.conf").write_text("changed-display")
        journal.write_text("newer-installation")
        policy.write_text('{"enabled":false,"keep":10}')
        restored = restore_host(result["archive"], state, runtime, self.maintenance, host_root=host)
        self.assertEqual(restored["state"], "completed")
        self.assertEqual((state / "elderbrain/secrets/admin.json").read_text(), '{"passwordHash":"test"}')
        self.assertEqual((runtime / "sway.conf").read_text(), "test")
        self.assertEqual(journal.read_text(), '{"credential":"saved-device-secret"}')
        self.assertEqual(journal.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(policy.read_text()), {'enabled': True, 'keep': 3})
        self.assertEqual(policy.stat().st_mode & 0o777, 0o600)
        with backup_archive.stage(restored["rollbackArchive"], parent=root) as (contents, _):
            self.assertEqual((contents / "elderbrain/secrets/admin.json").read_text(), "changed-secret")
            self.assertEqual((contents / "service-config/sway.conf").read_text(), "changed-display")
            self.assertEqual(json.loads((contents / 'service-config/checkpoint-retention.json').read_text()), {'enabled': False, 'keep': 10})
        self.assertEqual(recover_host(state, runtime, self.maintenance, host_root=host)["state"], "completed")
        legacy_restore = restore_host(legacy, state, runtime, self.maintenance, host_root=host)
        self.assertEqual(legacy_restore["state"], "completed")
        self.assertEqual(list(journals.iterdir()), [])
        self.assertEqual(json.loads(policy.read_text()), {'enabled': True, 'keep': 3})
        with backup_archive.stage(legacy_restore["rollbackArchive"], parent=root) as (contents, _):
            self.assertEqual((contents / "keypad-installations/private-plan.json").read_text(), '{"credential":"saved-device-secret"}')
        events = list(self.services.events)
        with self.assertRaisesRegex(ValueError, 'Retention requires'):
            restore_host(invalid_policy, state, runtime, self.maintenance, host_root=host)
        self.assertEqual(self.services.events, events)
        self.assertEqual(json.loads(policy.read_text()), {'enabled': True, 'keep': 3})
        with self.assertRaisesRegex(ValueError, 'TLS authority is invalid'):
            restore_host(invalid_ca, state, runtime, self.maintenance, host_root=host)
        self.assertEqual(self.services.events, events)
        (runtime / "VERSION").write_text("different-version")
        events = list(self.services.events)
        with self.assertRaisesRegex(ValueError, "appliance version"):
            restore_host(result["archive"], state, runtime, self.maintenance, host_root=host)
        self.assertEqual(self.services.events, events)


if __name__ == "__main__":
    unittest.main()
