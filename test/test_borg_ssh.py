"""Opt-in actual SSH transport, with temporary keys and a loopback-only server."""
import json
import os
from pathlib import Path
import pwd
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "appliance/lib"))
from borg_repository import BorgRepository
from backup_uploads import UploadStore
import backup_archive


@unittest.skipUnless(os.environ.get("ELDERBRAIN_TEST_BORG_SSH"), "requires opt-in Borg/SSH integration")
class BorgSSHTests(unittest.TestCase):
    def test_ssh_roundtrip_and_changed_host_key_rejection(self):
        binary = Path(os.environ["ELDERBRAIN_TEST_BORG_SSH"]).resolve()
        sshd = shutil.which("sshd")
        self.assertIsNotNone(sshd, "OpenSSH server is required")
        with tempfile.TemporaryDirectory(prefix="elderbrain-ssh-borg-") as temp:
            root = Path(temp)
            runtime = root / "runtime"
            runtime.mkdir()
            (runtime / "VERSION").write_text("ssh-test-version")
            remote = root / "remote"
            remote.mkdir()
            host_key = root / "host_key"
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(host_key)], check=True)
            host_public = " ".join(host_key.with_suffix(".pub").read_text().split()[:2])
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            user = pwd.getpwuid(os.getuid()).pw_name
            repository = BorgRepository(root, runtime, identity="ssh-fixture", executable=binary)
            repository.settings.configure({"kind": "ssh", "host": "127.0.0.1", "port": port,
                "user": user, "repository": str(remote / "repository"), "hostKey": host_public,
                "passphrase": "test-only-ssh-borg-password"})
            env = {"PATH": str(binary.parent) + os.pathsep + os.environ["PATH"],
                "BORG_CACHE_DIR": str(root / "cache"), "BORG_SECURITY_DIR": str(root / "security"),
                "BORG_KEYS_DIR": str(root / "keys"), "XDG_STATE_HOME": str(root / "xdg"),
                "XDG_CACHE_HOME": str(root / "xdg-cache")}
            with patch.dict(os.environ, env):
                repository.prepare()  # Generate the real client key and strict known_hosts.
                authorized = root / "authorized_keys"
                authorized.write_text((repository.settings.directory / "id_ed25519.pub").read_text())
                authorized.chmod(0o600)
                config = root / "sshd_config"
                config.write_text("\n".join([
                    f"Port {port}", "ListenAddress 127.0.0.1", f"HostKey {host_key}",
                    f"PidFile {root / 'sshd.pid'}", f"AuthorizedKeysFile {authorized}",
                    f"AllowUsers {user}", "PubkeyAuthentication yes", "AuthenticationMethods publickey",
                    "PasswordAuthentication no", "KbdInteractiveAuthentication no", "UsePAM no",
                    "StrictModes no", "PermitRootLogin prohibit-password", "PermitUserRC no",
                    "PermitTTY no", "DisableForwarding yes", "LogLevel ERROR",
                    f"ForceCommand {binary.parent / 'borg'} serve --restrict-to-path {remote}", "",
                ]))
                with (root / "sshd.log").open("wb") as log:
                    daemon = subprocess.Popen([sshd, "-D", "-e", "-f", str(config)], stdout=log, stderr=log)
                    try:
                        for _ in range(100):
                            if daemon.poll() is not None:
                                self.fail("Test sshd exited: " + (root / "sshd.log").read_text())
                            try:
                                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                                    break
                            except OSError:
                                time.sleep(0.05)
                        repository.initialize()
                        source = root / "source"
                        source.mkdir()
                        (source / "fixture.json").write_text('{"setting":"preserve over SSH"}')
                        archive = root / "manual.tar.zst"
                        manifest = backup_archive.create(archive, {"elderbrain": source}, version="ssh-test-version", identity="ssh-fixture")
                        repository.backup(lambda: {"archive": str(archive), "preview": backup_archive.preview(manifest)})
                        archives = repository.list_archives()
                        self.assertEqual(len(archives), 1)
                        uploaded = repository.fetch_archive(archives[0]["name"])
                        recovered, _ = UploadStore(root / "uploads").verify(uploaded["id"])
                        self.assertEqual(recovered.read_bytes(), archive.read_bytes())
                        kit = json.loads(Path(repository.recovery_kit()["archive"]).read_text())
                        replacement = BorgRepository(root / "replacement", runtime, identity="replacement", executable=binary)
                        replacement.settings.configure(kit["settings"])
                        for name, field in (("id_ed25519", "privateKey"), ("id_ed25519.pub", "publicKey"), ("known_hosts", "knownHosts")):
                            target = replacement.settings.directory / name
                            target.write_text(kit["ssh"][field])
                            target.chmod(0o600)
                        with patch.dict(os.environ, {"BORG_CACHE_DIR": str(root / "fresh-cache"),
                                "BORG_SECURITY_DIR": str(root / "fresh-security"), "BORG_KEYS_DIR": str(root / "fresh-keys")}):
                            self.assertEqual(replacement.list_archives(), archives)
                        wrong = root / "wrong_host_key"
                        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(wrong)], check=True)
                        settings = repository.settings.read()
                        settings["hostKey"] = " ".join(wrong.with_suffix(".pub").read_text().split()[:2])
                        repository.settings.configure(settings)
                        with self.assertRaises(subprocess.CalledProcessError):
                            repository.list_archives()
                    finally:
                        daemon.terminate()
                        try:
                            daemon.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            daemon.kill()
                            daemon.wait()
