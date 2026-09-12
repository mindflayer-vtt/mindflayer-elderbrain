"""Host backup coordinator. Never invoked with archive-provided commands or paths."""
import argparse
from contextlib import contextmanager, nullcontext
import fcntl
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid

import backup_archive


def save_record(path, record):
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(record, output)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Maintenance:
    """Persist service state before stopping anything; failed recovery blocks reuse."""
    def __init__(self, directory, services):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.journal = self.directory / "maintenance.json"
        self.services = services

    @contextmanager
    def locked(self):
        fd = os.open(self.directory / "maintenance.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError("Another maintenance operation is running") from error
            yield fd
        finally:
            os.close(fd)

    def previous(self):
        return json.loads(self.journal.read_text()) if self.journal.exists() else {}

    def recover(self):
        with self.locked():
            record = self.previous()
            if record.get('operation') in ('update', 'baseline'):
                raise RuntimeError('Update recovery must resolve runtime and checkpoint state before starting services')
            if record.get("operation") in ("restore", "network-restore"):
                raise RuntimeError("Restore recovery must roll back configuration before starting services")
            if record.get("state") not in ("stopping", "working", "starting", "recovery-required"):
                return {"state": "no-recovery-needed"}
            self.services.resume(record["services"])
            record["state"] = "recovered"
            save_record(self.journal, record)
            return record

    @contextmanager
    def window(self, operation, exclusive=nullcontext):
        with self.locked():
            if self.previous().get("state") not in (None, "completed", "failed", "recovered", "rolled-back"):
                raise RuntimeError("Interrupted maintenance requires backup-recover before continuing")
            record = {"operation": operation, "id": uuid.uuid4().hex,
                      "startedAt": time.time(), "services": self.services.snapshot(), "state": "stopping"}
            save_record(self.journal, record)
            succeeded = False
            try:
                with exclusive():
                    self.services.stop(record["services"])
                    record["state"] = "working"
                    save_record(self.journal, record)
                    yield record
                    succeeded = True
            finally:
                record["state"] = "starting"
                save_record(self.journal, record)
                try:
                    self.services.resume(record["services"])
                except Exception:
                    record["state"] = "recovery-required"
                    save_record(self.journal, record)
                    raise
                record["state"] = "completed" if succeeded else "failed"
                record["finishedAt"] = time.time()
                save_record(self.journal, record)


class HostServices:
    ALLOWED = {"elderbrain-setup", "mindflayer-server", "foundry", "traefik"}

    def __init__(self, runtime):
        self.runtime = runtime
        self.compose = ["docker", "compose", "--env-file", str(runtime / "appliance.env"),
                        "-f", str(runtime / "compose.yaml"), "--profile", "foundry"]

    def run(self, args, *, check=True):
        return subprocess.run(args, check=check, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=180)

    def snapshot(self):
        running = self.run([*self.compose, "ps", "--status", "running", "--services"]).stdout.split()
        if not set(running) <= self.ALLOWED:
            raise ValueError("Unexpected compose services")
        graphics = self.run(["systemctl", "is-active", "elderbrain-graphics.service"], check=False).returncode == 0
        project = None
        if running:
            ids = self.run([*self.compose, "ps", "--status", "running", "-q"]).stdout.split()
            projects = {self.run(["docker", "inspect", "--format",
                                  '{{index .Config.Labels "com.docker.compose.project"}}', identity]).stdout.strip()
                        for identity in ids}
            if len(projects) != 1:
                raise ValueError("Cannot identify a unique running Compose project")
            project = projects.pop()
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,127}", project):
                raise ValueError("Invalid Compose project identity")
        return {"compose": running, "graphics": graphics, "project": project}

    def checked(self, saved):
        if not isinstance(saved.get("compose"), list) or not set(saved["compose"]) <= self.ALLOWED:
            raise ValueError("Invalid saved service state")

    def validate(self):
        self.run([*self.compose, "config", "--quiet"])
        self.run(["sshd", "-t"])

    def resume_restored(self, saved):
        self.checked(saved)
        self.run(["systemctl", "daemon-reload"])
        self.run(["python3", str(self.runtime / "borg_service.py"), "schedule"])
        # Refresh local CA trust after replacing Traefik certificates.
        self.run([str(self.runtime / "prepare-admin")])
        if saved["compose"]:
            self.run([*self.compose, "up", "-d", "--no-build", "--no-deps",
                      "--force-recreate", "--wait", "--wait-timeout", "120", *saved["compose"]])
        self.run(["systemctl", "reload", "ssh.service"])
        self.resume(saved)

    def stop(self, saved):
        self.checked(saved)
        if saved["graphics"]:
            self.run(["systemctl", "stop", "elderbrain-graphics.service"])
        if saved["compose"]:
            project = saved.get("project")
            if not isinstance(project, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,127}", project):
                raise ValueError("Missing saved project identity; manual service diagnosis required")
            # Do not parse a possibly broken restored Compose file during recovery.
            # Include recreated containers, whose IDs may differ from the snapshot.
            ids = self.run(["docker", "ps", "-q", "--filter", "label=com.docker.compose.project=" + project]).stdout.split()
            if ids:
                self.run(["docker", "stop", "--time", "60", *ids])

    def resume(self, saved):
        self.checked(saved)
        if saved["compose"]:
            self.run([*self.compose, "start", *saved["compose"]])
            deadline = time.monotonic() + 120
            while True:
                healthy = True
                for service in saved["compose"]:
                    ids = self.run([*self.compose, "ps", "-a", "-q", service]).stdout.split()
                    if len(ids) != 1:
                        healthy = False
                        continue
                    state = json.loads(self.run(["docker", "inspect", "--format", "{{json .State}}", ids[0]]).stdout)
                    healthy &= state.get("Running", False) and state.get("Health", {}).get("Status", "healthy") == "healthy"
                if healthy:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("Services did not become healthy; run backup-recover after diagnosis")
                time.sleep(2)
        if saved["graphics"]:
            self.run(["systemctl", "start", "elderbrain-graphics.service"])
            self.run(["systemctl", "is-active", "elderbrain-graphics.service"])


def create_backup(destination, state, runtime, maintenance, *, host_root=Path("/"), operation=None, passphrase=None):
    if passphrase is not None:
        from backup_crypto import validate_passphrase
        validate_passphrase(passphrase)
    destination = Path(destination)
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    # A restore supplies its existing locked, stopped-writer operation so its
    # rollback archive does not open a nested maintenance window.
    with (maintenance.window("backup") if operation is None else nullcontext(operation)) as operation:
        with tempfile.TemporaryDirectory(prefix="elderbrain-config-", dir=destination) as temp:
            managed = Path(temp) / "service-config"
            managed.mkdir(mode=0o700)
            for name in ("appliance.env", "compose.yaml", "VERSION", "sway.conf"):
                shutil.copy2(runtime / name, managed / name)
            # Export policy only, never snapshot trees, pins or deletion journals.
            # The maintenance lock excludes policy writes and restore activation.
            from local_snapshots import Snapshots
            policy = Snapshots(state, quiesce=None).read_retention()
            save_record(managed / 'checkpoint-retention.json', policy)
            units = managed / "systemd"
            units.mkdir()
            for name in ("elderbrain-stack.service", "elderbrain-management.service", "elderbrain-graphics.service", "elderbrain-backup.service"):
                shutil.copy2(host_root / "etc/systemd/system" / name, units / name)
            sources = {name: state / name for name in
                       ("foundry", "elderbrain", "mindflayer", "firmware", "traefik", "browser")}
            (state / "keypad-installations").mkdir(mode=0o700, exist_ok=True)
            sources["keypad-installations"] = state / "keypad-installations"
            sources["service-config"] = managed
            sources["ssh-server"] = host_root / "etc/ssh"
            for name, source in (("ssh-root", host_root / "root/.ssh"),
                                 ("ssh-admin", host_root / "home/elderbrain-installer/.ssh")):
                if source.exists():
                    sources[name] = source
            sources['admin-ca'] = state / 'host/admin-ca'
            archive = destination / ("elderbrain-" + operation["id"] + ".tar.zst")
            manifest = backup_archive.create(archive, sources, version=(runtime / "VERSION").read_text().strip(),
                                             identity=(host_root / "etc/machine-id").read_text().strip())
    if passphrase is not None:
        from backup_crypto import transform
        archive = transform(archive, Path(str(archive) + ".gpg"), passphrase)
    return {"archive": str(archive), "preview": backup_archive.preview(manifest), "encrypted": passphrase is not None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("backup", "preview", "recover", "restore", "restore-recover"))
    parser.add_argument("path", nargs="?")
    parser.add_argument("--confirm-restore", action="store_true")
    parser.add_argument("--encrypted", action="store_true")
    parser.add_argument("--passphrase-fd", type=int)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("must run as root")
    state = Path(os.environ.get("ELDERBRAIN_STATE_DIR", "/var/lib/mindflayer-elderbrain"))
    runtime = Path(os.environ.get("ELDERBRAIN_COMPOSE_DIR", "/opt/mindflayer-elderbrain"))
    maintenance = Maintenance(state / "maintenance", HostServices(runtime))
    passphrase = None
    if args.encrypted:
        from backup_crypto import validate_passphrase
        if args.passphrase_fd is None:
            import getpass
            passphrase = getpass.getpass("Backup encryption passphrase: ")
        else:
            with os.fdopen(os.dup(args.passphrase_fd), "r") as password_input:
                passphrase = password_input.read(8193).removesuffix("\n")
        validate_passphrase(passphrase)
    if args.action == "backup":
        result = create_backup(args.path or state / "backups", state, runtime, maintenance, passphrase=passphrase)
    elif args.action == "recover":
        result = maintenance.recover()
    elif args.action in ("restore", "restore-recover"):
        from restore_service import restore_host, recover_host
        if args.action == "restore-recover":
            result = recover_host(state, runtime, maintenance)
        else:
            if not args.path or not args.confirm_restore:
                parser.error("restore requires ARCHIVE --confirm-restore; inspect with backup-preview first")
            if args.encrypted:
                from backup_crypto import decrypted
                with decrypted(args.path, passphrase, parent=maintenance.directory) as plain:
                    result = restore_host(plain, state, runtime, maintenance)
            else:
                result = restore_host(args.path, state, runtime, maintenance)
    else:
        if not args.path:
            parser.error("preview requires an archive path")
        if args.encrypted:
            from backup_crypto import decrypted
            with decrypted(args.path, passphrase, parent=maintenance.directory) as plain:
                result = backup_archive.preview(backup_archive.validate(plain))
        else:
            result = backup_archive.preview(backup_archive.validate(args.path))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
