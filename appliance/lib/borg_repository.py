"""Scoped Borgmatic operations. Repository access never uses caller shell text."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone

from backup_service import save_record
import backup_archive
from backup_uploads import UploadStore
from borg_settings import BorgSettings


def private_text(path, value):
    fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write(value)
        output.flush()
        os.fsync(output.fileno())


class BorgRepository:
    def __init__(self, state, runtime, *, identity, executable=None, mountpoint=Path("/mnt/elderbrain-backup")):
        self.state, self.runtime = Path(state), Path(runtime)
        self.settings = BorgSettings(state)
        self.identity = identity
        self.executable = str(executable or self.runtime / "borgmatic-venv/bin/borgmatic")
        self.mountpoint = Path(mountpoint)
        self.config = self.settings.directory / "borgmatic.yaml"

    @contextmanager
    def locked(self):
        fd = os.open(self.state / "borg.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError("Another repository operation is running") from error
            yield
        finally:
            os.close(fd)

    def run(self, command, *, check=True, timeout=180):
        return subprocess.run(command, check=check, text=True, capture_output=True,
                              stdin=subprocess.DEVNULL, timeout=timeout)

    def attempt_timeout(self):
        settings = self.settings.read()
        timeout = settings.get("attemptTimeoutSeconds", 300) if settings else 300
        if type(timeout) is not int or not 30 <= timeout <= 1800:
            raise ValueError("Invalid repository attempt timeout")
        return timeout

    def deadline(self):
        return time.monotonic() + self.attempt_timeout()

    @staticmethod
    def remaining(deadline):
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError("Backup attempt exceeded its configured time limit")
        return value

    def ensure_nfs(self, settings, *, deadline=None):
        expected = settings["host"] + ":" + settings["export"]
        if self.mountpoint.resolve() != self.mountpoint:
            raise ValueError("NFS mountpoint cannot be a symbolic link")
        self.mountpoint.mkdir(mode=0o700, parents=True, exist_ok=True)
        timeout = self.remaining(deadline) if deadline is not None else 180
        result = self.run(["findmnt", "--json", "--mountpoint", str(self.mountpoint)], check=False,
                          timeout=timeout)
        if result.returncode:
            if any(self.mountpoint.iterdir()):
                raise ValueError("Refusing to cover non-empty local directory with an NFS mount")
            self.run(["mount", "-t", "nfs", "-o", "hard,nodev,nosuid,noexec", expected,
                      str(self.mountpoint)], timeout=self.remaining(deadline) if deadline is not None else 180)
            result = self.run(["findmnt", "--json", "--mountpoint", str(self.mountpoint)],
                              timeout=self.remaining(deadline) if deadline is not None else 180)
        mounts = json.loads(result.stdout).get("filesystems", [])
        if (len(mounts) != 1 or mounts[0].get("fstype") not in ("nfs", "nfs4")
                or mounts[0].get("source") != expected or mounts[0].get("target") != str(self.mountpoint)):
            raise ValueError("Configured NFS export is not mounted; refusing local-disk fallback")
        repository = self.mountpoint / settings["repository"]
        if repository.resolve() != repository or not repository.is_relative_to(self.mountpoint):
            raise ValueError("Repository path escapes its verified NFS mount")

    def prepare(self, *, deadline=None):
        settings = self.settings.read()
        if settings is None:
            raise ValueError("Configure a backup destination first")
        staging = self.state / "borg-staging"
        if staging.is_symlink():
            raise ValueError("Invalid Borg staging directory")
        staging.mkdir(mode=0o700, exist_ok=True)
        if settings["kind"] == "nfs":
            self.ensure_nfs(settings, deadline=deadline)
        else:
            key = self.settings.directory / "id_ed25519"
            if not key.exists():
                self.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
                         timeout=self.remaining(deadline) if deadline is not None else 180)
            endpoint = settings["host"] if settings["port"] == 22 else f'[{settings["host"]}]:{settings["port"]}'
            private_text(self.settings.directory / "known_hosts", endpoint + " " + settings["hostKey"] + "\n")
        config = self.settings.render(settings, self.identity, (self.runtime / "VERSION").read_text().strip())
        if settings["kind"] == "nfs":
            config["repositories"][0]["path"] = str(self.mountpoint / settings["repository"])
        save_record(self.config, config)
        self.run([self.executable, "--config", str(self.config), "config", "validate"],
                 timeout=self.remaining(deadline) if deadline is not None else 180)
        return config

    def action(self, *arguments, deadline=None):
        timeout = self.remaining(deadline) if deadline is not None else self.attempt_timeout()
        return self.run([self.executable, "--config", str(self.config), *arguments], timeout=timeout)

    def initialize(self):
        with self.locked():
            self.prepare()
            version = self.run(["borg", "--version"]).stdout.strip()
            # This release deliberately targets stable Borg 1 repositories.
            if not re.match(r"borg 1\.", version):
                raise ValueError("Borg 1.x is required for this repository format")
            self.action("repo-create", "--encryption", "repokey-blake2")
            return {"state": "initialized"}

    def list_archives(self):
        with self.locked():
            self.prepare()
            # Default Borgmatic matching derives from archive_name_format and
            # would hide older versions or another appliance's recovery archives.
            result = json.loads(self.action("repo-list", "--json", "--match-archives", "sh:elderbrain-*").stdout)
            # Borgmatic emits a list of per-repository JSON responses.
            repositories = result if isinstance(result, list) else [result]
            archives = []
            for repository in repositories:
                for archive in repository.get("archives", []):
                    name = archive.get("name", archive.get("archive", ""))
                    if re.fullmatch(r"elderbrain-[A-Za-z0-9_.:+-]{1,200}", name):
                        parts = name.removeprefix("elderbrain-").split("--", 2)
                        archives.append({"name": name, "id": archive.get("id"), "time": archive.get("time", archive.get("start")),
                                         "applianceIdentity": parts[0] if len(parts) == 3 else "unknown",
                                         "applianceVersion": parts[1] if len(parts) == 3 else "unknown"})
            return archives

    def transfer_locked(self, snapshot, *, deadline):
        archive = Path(snapshot["archive"])
        if (archive.parent != self.state / "backups" or archive.resolve() != archive
                or not re.fullmatch(r"elderbrain-[a-f0-9]{32}\.tar\.zst", archive.name)):
            raise ValueError("Remote backup source is not a canonical local archive")
        manifest = backup_archive.validate(archive, deadline=deadline)
        preview = backup_archive.preview(manifest)
        staging = self.state / "borg-staging"
        if staging.is_symlink():
            raise ValueError("Invalid Borg staging directory")
        staging.mkdir(mode=0o700, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".snapshot-", dir=staging)
        incoming = Path(temporary)
        try:
            with os.fdopen(fd, "wb") as target, open(archive, "rb") as source:
                while chunk := source.read(1024 * 1024):
                    self.remaining(deadline)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            os.replace(incoming, staging / "appliance.tar.zst")
        finally:
            incoming.unlink(missing_ok=True)
        save_record(staging / "metadata.json", preview)
        self.action("create", deadline=deadline)
        # Never prune before a new archive has been successfully created.
        self.action("prune", deadline=deadline)
        self.action("compact", deadline=deadline)
        return {"state": "completed", "preview": preview}

    def transfer(self, snapshot, *, deadline=None):
        """Retry one exact, already captured local archive."""
        deadline = deadline or self.deadline()
        with self.locked():
            self.prepare(deadline=deadline)
            return self.transfer_locked(snapshot, deadline=deadline)

    def backup(self, create_snapshot):
        """Capture a consistent local archive, then transfer after services resume."""
        deadline = self.deadline()
        with self.locked():
            self.prepare(deadline=deadline)
            return self.transfer_locked(create_snapshot(deadline), deadline=deadline)

    def fetch_archive(self, name):
        if not isinstance(name, str) or not re.fullmatch(r"elderbrain-[A-Za-z0-9_.:+-]{1,200}", name):
            raise ValueError("Invalid archive name")
        with self.locked():
            self.prepare()
            with tempfile.TemporaryDirectory(prefix="borg-extract-", dir=self.state) as temp:
                self.action("extract", "--archive", name, "--path", "appliance.tar.zst", "--destination", temp)
                fd = os.open(Path(temp) / "appliance.tar.zst", os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, "rb") as data:
                    info = os.fstat(data.fileno())
                    if not stat.S_ISREG(info.st_mode):
                        raise ValueError("Remote archive does not contain a regular backup file")
                    # Same private-upload validation and restore engine as manual files.
                    return UploadStore(self.state / "uploads").receive(data, info.st_size)

    def recovery_kit(self):
        with self.locked():
            config = self.prepare()
            with tempfile.TemporaryDirectory(prefix="borg-key-export-", dir=self.state) as temp:
                exported = Path(temp) / "repository-key"
                self.action("key", "export", "--path", str(exported))
                if exported.is_symlink() or not exported.is_file() or exported.stat().st_size > 1024 * 1024:
                    raise ValueError("Invalid repository key export")
                settings = self.settings.read()
                ssh = None
                if settings["kind"] == "ssh":
                    ssh = {"privateKey": (self.settings.directory / "id_ed25519").read_text(),
                           "publicKey": (self.settings.directory / "id_ed25519.pub").read_text(),
                           "knownHosts": (self.settings.directory / "known_hosts").read_text()}
                kit = {"format": 1, "type": "elderbrain-borg-recovery-kit", "containsSecrets": True,
                       "createdAt": datetime.now(timezone.utc).isoformat(), "applianceIdentity": self.identity,
                       "applianceVersion": (self.runtime / "VERSION").read_text().strip(),
                       "repository": config["repositories"][0]["path"], "settings": settings,
                       "ssh": ssh, "borgRepositoryKey": exported.read_text(),
                       "instructions": [
                           "Keep this unencrypted file offline and private. Anyone with it can access and decrypt your repository.",
                           "Install the recorded Elderbrain version on a replacement appliance. Configure the same repository with settings.passphrase; do not initialize a new repository.",
                           "For SSH, restore privateKey to elderbrain/secrets/borg/id_ed25519 (0600), publicKey to id_ed25519.pub, and knownHosts to known_hosts. Verify the server identity independently.",
                           "For NFS, configure the recorded host/export and mount it before accessing the repository. The absolute repository path refers to the appliance mountpoint.",
                           "If repository key metadata was lost, save borgRepositoryKey to a private file and use Borg 1 key import for the existing repository. The passphrase remains settings.passphrase.",
                           "Test repository access, list archives, retrieve a restore preview, then confirm restoration. Application credentials will revert to those in the restored archive.",
                       ]}
                directory = self.state / "recovery-kits"
                directory.mkdir(mode=0o700, exist_ok=True)
                artifact = directory / ("elderbrain-" + uuid.uuid4().hex + ".json")
                save_record(artifact, kit)
                return {"state": "completed", "archive": str(artifact)}
