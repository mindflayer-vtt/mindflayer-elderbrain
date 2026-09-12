"""Borg CLI entry points, scheduling, and shared restore preview integration."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

import backup_archive
from backup_service import HostServices, Maintenance, create_backup
from backup_uploads import UploadStore
from borg_repository import BorgRepository, private_text
from borg_settings import BorgSettings


def automatic_enabled(settings):
    return settings is not None and (settings.get("enabled", False) or settings.get("onBoot", False))


def activate_schedule(repository, *, unit_directory=Path("/etc/systemd/system")):
    settings = repository.settings.read()
    if settings is None:
        repository.run(["systemctl", "disable", "--now", "elderbrain-backup.timer"], check=False)
        return {"state": "unconfigured"}
    if not automatic_enabled(settings):
        repository.run(["systemctl", "disable", "--now", "elderbrain-backup.timer"], check=False)
        return {"state": "disabled"}
    private_text(unit_directory / "elderbrain-backup.timer", repository.settings.timer())
    repository.run(["systemctl", "daemon-reload"])
    repository.run(["systemctl", "enable", "elderbrain-backup.timer"])
    repository.run(["systemctl", "restart", "elderbrain-backup.timer"])
    return {"state": "enabled"}


def public_settings(repository):
    result = repository.settings.public()
    from backup_pending import public_status
    result["pendingBackup"] = public_status(repository.state)
    public_key = repository.settings.directory / "id_ed25519.pub"
    result["sshPublicKey"] = public_key.read_text().strip() if public_key.is_file() else ""
    return result


def configure(repository, data, *, unit_directory=Path("/etc/systemd/system")):
    with repository.locked():
        repository.settings.configure(data)
        if data["kind"] == "ssh":
            key = repository.settings.directory / "id_ed25519"
            if not key.exists():
                repository.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)])
        activate_schedule(repository, unit_directory=unit_directory)
        return public_settings(repository)


def execute(action, repository, *, archive=None):
    if action == "settings":
        return public_settings(repository)
    if action == "schedule":
        return activate_schedule(repository)
    if action == "init":
        return repository.initialize()
    if action == "recovery-kit":
        return repository.recovery_kit()
    if action in ("test", "list"):
        archives = repository.list_archives()
        return {"state": "connected", "archives": archives}
    if action == "backup":
        maintenance = Maintenance(repository.state / "maintenance", HostServices(repository.runtime))
        return repository.backup(lambda deadline: create_backup(
            repository.state / "backups", repository.state, repository.runtime, maintenance,
            deadline=deadline))
    if action == "fetch":
        uploaded = repository.fetch_archive(archive)
        path, checksum = UploadStore(repository.state / "uploads").verify(uploaded["id"])
        preview = backup_archive.preview(backup_archive.validate(path))
        return {"state": "validated", "uploadId": uploaded["id"], "sha256": checksum, "preview": preview}
    raise ValueError("Unsupported repository operation")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("settings", "configure", "schedule", "scheduled", "init", "test", "list", "backup", "fetch", "recovery-kit"))
    parser.add_argument("archive", nargs="?")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("must run as root")
    state = Path(os.environ.get("ELDERBRAIN_STATE_DIR", "/var/lib/mindflayer-elderbrain"))
    runtime = Path(os.environ.get("ELDERBRAIN_COMPOSE_DIR", "/opt/mindflayer-elderbrain"))
    repository = BorgRepository(state, runtime, identity=Path("/etc/machine-id").read_text().strip())
    if args.action == "configure":
        value = sys.stdin.read(65537)
        if len(value) > 65536:
            parser.error("settings input too large")
        result = configure(repository, json.loads(value))
    elif args.action == "scheduled":
        from host_jobs import JobStore
        if not automatic_enabled(repository.settings.read()):
            result = {"state": "disabled"}
        else:
            jobs = JobStore(state / "jobs")
            job = jobs.submit("borg-backup")
            # Keep the systemd service alive so it owns and supervises the worker.
            while job["state"] in ("queued", "running"):
                time.sleep(1)
                job = jobs.read(job["id"])
            print(json.dumps(job))
            raise SystemExit(0 if job["state"] == "completed" else 1)
    else:
        result = execute(args.action, repository, archive=args.archive)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
