"""Durable pre-power backup protection and exact-archive boot retry."""
from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import re
import stat
import time
import uuid

import backup_archive
from backup_service import create_backup, create_checkpoint_backup, save_record
from borg_repository import BorgRepository
from borg_settings import BorgSettings
from local_snapshots import Snapshots


def validate_record(value):
    if (not isinstance(value, dict) or value.get("format") != 1
            or not re.fullmatch(r"[a-f0-9]{32}", value.get("id", ""))
            or not re.fullmatch(r"[a-f0-9]{32}", value.get("checkpoint", ""))
            or value.get("state") not in ("checkpoint-ready", "pending-upload", "uploaded", "completed")
            or type(value.get("createdAt")) not in (int, float)
            or not math.isfinite(value["createdAt"])):
        raise ValueError("Invalid pending backup record")
    for name in ("lastFailureAt", "uploadedAt", "completedAt"):
        if name in value and (type(value[name]) not in (int, float) or not math.isfinite(value[name])):
            raise ValueError("Invalid pending backup timestamp")
    archive = value.get("archive")
    if archive is not None and (not isinstance(archive, str)
            or archive != "elderbrain-" + value["id"] + ".tar.zst"):
        raise ValueError("Invalid pending backup archive")
    return value


def read_path(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor) as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_size > 8192):
            raise ValueError("Unsafe pending backup record")
        return validate_record(json.load(stream))


def read_records(state):
    directory = Path(state) / "pending-backup"
    if not directory.exists():
        return []
    info = directory.lstat()
    if (not stat.S_ISDIR(info.st_mode) or directory.resolve() != directory
            or info.st_uid != os.geteuid() or info.st_mode & 0o077):
        raise ValueError("Pending backup state must be private")
    result = []
    for path in directory.glob("*.json"):
        if not re.fullmatch(r"[a-f0-9]{32}\.json", path.name):
            raise ValueError("Unexpected pending backup record")
        value = read_path(path)
        if path.stem != value["id"]:
            raise ValueError("Pending backup record filename mismatch")
        result.append(value)
    return sorted(result, key=lambda value: (value["createdAt"], value["id"]))


def read_record(state):
    records = read_records(state)
    pending = [value for value in records if value["state"] != "completed"]
    return pending[0] if pending else (records[-1] if records else None)


def public_status(state):
    records = read_records(state)
    pending = [value for value in records if value["state"] != "completed"]
    value = pending[0] if pending else (records[-1] if records else None)
    if value is None:
        return {"state": "none", "pendingCount": 0}
    result = {key: value[key] for key in
              ("state", "checkpoint", "createdAt", "lastFailureAt", "completedAt") if key in value}
    result["pendingCount"] = len(pending)
    return result


@contextmanager
def record_lock(directory, identity):
    descriptor = os.open(Path(directory) / (identity + ".lock"),
                         os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Pending backup generation is already being retried") from error
        yield
    finally:
        os.close(descriptor)


class PendingBackup:
    def __init__(self, state, runtime, *, host_root=Path("/"), snapshots=None, repository=None):
        self.state, self.runtime, self.host_root = Path(state), Path(runtime), Path(host_root)
        self.directory = self.state / "pending-backup"
        if snapshots is None:
            from snapshot_service import store
            snapshots = store(self.state, self.runtime)
        self.snapshots = snapshots
        if repository is None:
            identity = (self.host_root / "etc/machine-id").read_text().strip()
            repository = BorgRepository(self.state, self.runtime, identity=identity)
        self.repository = repository

    def read(self):
        return read_record(self.state)

    def write(self, record):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or self.directory.resolve() != self.directory
                or info.st_uid != os.geteuid() or info.st_mode & 0o077):
            raise ValueError("Pending backup state must be private")
        record = validate_record(record)
        save_record(self.directory / (record["id"] + ".json"), record)

    def recover_pin(self):
        """Reconstruct records lost after their purpose-bound pins were published."""
        pinned = self.snapshots.pinned_records("pending-backup")
        if not pinned:
            return None
        existing = {(value["checkpoint"], value["id"]) for value in read_records(self.state)}
        recovered = []
        for value in pinned:
            pin, checkpoint = value["pin"], value["checkpoint"]
            if checkpoint["reason"] != "before-shutdown":
                raise ValueError("Pending backup pin has no complete shutdown checkpoint")
            if (pin["id"], pin["owner"]) not in existing:
                record = {"format": 1, "id": pin["owner"], "checkpoint": pin["id"],
                          "state": "checkpoint-ready", "createdAt": checkpoint["createdAt"]}
                self.write(record)
                recovered.append(record)
        return min(recovered, key=lambda value: (value["createdAt"], value["id"])) if recovered else None

    def capture(self, owner):
        if not re.fullmatch(r"[a-f0-9]{32}", owner):
            raise ValueError("Invalid pending backup owner")
        existing = [value for value in read_records(self.state) if value["id"] == owner]
        if existing:
            if existing[0]["state"] == "completed":
                raise ValueError("Power operation already completed backup protection")
            return self.retry(existing[0])
        checkpoint = self.snapshots.create("before-shutdown", owner=owner, purpose="pending-backup")
        record = {"format": 1, "id": owner, "checkpoint": checkpoint["id"],
                  "state": "checkpoint-ready", "createdAt": time.time()}
        self.write(record)
        return self.retry(record)

    def retry(self, record=None):
        self.recover_pin()
        record = record or self.read()
        if record is None:
            return {"state": "nothing-pending"}
        record = validate_record(record)
        with record_lock(self.directory, record["id"]):
            stored = self.directory / (record["id"] + ".json")
            if stored.exists():
                record = read_path(stored)
            if record["state"] == "completed":
                return record
            matches = [value for value in self.snapshots.pinned_records("pending-backup")
                       if value["pin"]["id"] == record["checkpoint"]
                       and value["pin"]["owner"] == record["id"]]
            if len(matches) > 1 or (matches and matches[0]["checkpoint"]["reason"] != "before-shutdown"):
                raise ValueError("Pending backup record has no matching shutdown checkpoint pin")
            if record["state"] != "uploaded" and len(matches) != 1:
                raise ValueError("Pending backup record has no matching shutdown checkpoint pin")
            deadline = self.repository.deadline()
            try:
                snapshot = None
                if record.get("archive") is None:
                    expected = self.state / "backups" / ("elderbrain-" + record["id"] + ".tar.zst")
                    if expected.exists():
                        manifest = backup_archive.validate(expected, deadline=deadline)
                        snapshot = {"archive": str(expected), "preview": backup_archive.preview(manifest)}
                    else:
                        snapshot = create_checkpoint_backup(self.state / "backups", self.state, self.runtime,
                            record["checkpoint"], record, host_root=self.host_root, deadline=deadline)
                    record.update(state="pending-upload", archive=Path(snapshot["archive"]).name,
                                  preview=snapshot["preview"])
                    self.write(record)
                else:
                    snapshot = {"archive": str(self.state / "backups" / record["archive"])}
                if record["state"] != "uploaded":
                    transferred = self.repository.transfer(snapshot, deadline=deadline)
                    record["preview"] = transferred["preview"]
                    record.update(state="uploaded", uploadedAt=time.time())
                    self.write(record)
            except Exception:
                record["lastFailureAt"] = time.time()
                self.write(record)
                return record
            if matches:
                self.snapshots.unpin(record["checkpoint"], record["id"], "pending-backup")
            record.update(state="completed", completedAt=time.time())
            record.pop("lastFailureAt", None)
            self.write(record)
            if record.get("archive"):
                (self.state / "backups" / record["archive"]).unlink(missing_ok=True)
            return record


def protect(state, runtime, owner=None, *, host_root=Path("/"), snapshots=None, repository=None):
    settings = BorgSettings(state).read()
    if settings is None or not settings.get("onShutdown", False):
        if snapshots is None:
            from snapshot_service import store
            snapshots = store(state, runtime)
        checkpoint = snapshots.create("before-shutdown")
        return {"state": "local-checkpoint", "checkpoint": checkpoint["id"]}
    owner = owner or uuid.uuid4().hex
    pending = PendingBackup(state, runtime, host_root=host_root, snapshots=snapshots,
                            repository=repository)
    return pending.capture(owner)


def protect_update(state, runtime, maintenance, record, *, host_root=Path("/"), repository=None):
    """Attempt configured remote protection after the mandatory update checkpoint."""
    settings = BorgSettings(state).read()
    if settings is None or not settings.get("beforeUpdate", False):
        result = {"state": "not-requested"}
        record["remoteBackup"] = result
        return result
    if repository is None:
        identity = (Path(host_root) / "etc/machine-id").read_text().strip()
        repository = BorgRepository(state, runtime, identity=identity)
    result = {"state": "failed", "failurePolicy": settings.get("updateFailurePolicy", "continue")}
    try:
        transferred = repository.backup(lambda deadline: create_backup(
            Path(state) / "backups", state, runtime, maintenance,
            operation=record, host_root=host_root, deadline=deadline))
        result = {"state": transferred["state"], "failurePolicy": result["failurePolicy"]}
    except Exception as error:
        record["remoteBackup"] = result
        if result["failurePolicy"] == "block":
            raise RuntimeError("Configured pre-update remote backup failed") from error
        return result
    record["remoteBackup"] = result
    return result


def retry(state=Path("/var/lib/mindflayer-elderbrain"), runtime=Path("/opt/mindflayer-elderbrain")):
    settings = BorgSettings(state).read()
    pending = PendingBackup(state, runtime)
    pending.recover_pin()
    record = pending.read()
    if record is None or record["state"] == "completed":
        return {"state": "nothing-pending"}
    if settings is None:
        return {"state": "pending-configuration"}
    return pending.retry(record)


if __name__ == "__main__":
    if os.geteuid() != 0:
        raise SystemExit("Pending backup recovery requires root")
    print(json.dumps(retry()))
