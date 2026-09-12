"""Journaled replacement of fixed restore targets, with retained rollback trees.

The host coordinator must hold the maintenance lock and stop all writers before
prepare/apply/rollback. Archive paths must never supply the target mapping.
"""
import os
from pathlib import Path
import shutil
import uuid

from backup_service import save_record
import json


def sync_directory(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def copy_owned(source, destination):
    if source.is_symlink():
        raise ValueError("Restore source root cannot be a symbolic link")
    if source.is_dir():
        shutil.copytree(source, destination, symlinks=True)
        paths = [source, *source.rglob("*")]
    elif source.is_file():
        shutil.copy2(source, destination)
        paths = [source]
    else:
        raise ValueError("Restore source must be a regular file or directory")
    for path in sorted(paths, key=lambda p: len(p.parts), reverse=True):
        target = destination if path == source else destination / path.relative_to(source)
        metadata = path.lstat()
        actual = target.lstat()
        if (actual.st_uid, actual.st_gid) != (metadata.st_uid, metadata.st_gid):
            os.chown(target, metadata.st_uid, metadata.st_gid, follow_symlinks=False)
            if not target.is_symlink():
                os.chmod(target, metadata.st_mode & 0o7777)
        if target.is_file() and not target.is_symlink():
            with target.open("rb") as data:
                os.fsync(data.fileno())
        elif target.is_dir() and not target.is_symlink():
            sync_directory(target)


class RestoreTransaction:
    def __init__(self, journal, targets):
        self.journal = Path(journal)
        self.targets = {key: Path(value).absolute() for key, value in targets.items()}
        if not self.targets:
            raise ValueError("Restore needs explicit targets")
        for key, target in self.targets.items():
            if (not key or len(target.parts) < 3 or target.resolve() != target
                    or not target.parent.is_dir() or target.is_mount()):
                raise ValueError("Unsafe restore target")
            if any(other != key and (target == path or target.is_relative_to(path))
                   for other, path in self.targets.items()):
                raise ValueError("Restore targets overlap")
            if self.journal.absolute().is_relative_to(target):
                raise ValueError("Restore journal cannot be inside a target")

    def read(self):
        record = json.loads(self.journal.read_text())
        if record.get("targets") != {key: str(path) for key, path in self.targets.items()}:
            raise ValueError("Restore target mapping changed; operator recovery required")
        identity = record.get("id", "")
        if len(identity) != 32 or any(c not in "0123456789abcdef" for c in identity):
            raise ValueError("Invalid restore transaction identity")
        if set(record.get("existed", {})) != set(self.targets):
            raise ValueError("Invalid restore transaction record")
        return record

    def location(self, record, key):
        target = self.targets[key]
        return target.parent / (".elderbrain-restore-" + record["id"] + "-" + target.name)

    def prepare(self, sources):
        if self.journal.exists():
            raise ValueError("Restore journal already exists; use a new transaction")
        if set(sources) != set(self.targets):
            raise ValueError("Restore sources do not match fixed targets")
        record = {"id": uuid.uuid4().hex, "state": "preparing",
                  "targets": {key: str(path) for key, path in self.targets.items()},
                  "existed": {key: path.exists() for key, path in self.targets.items()}}
        save_record(self.journal, record)
        for key in self.targets:
            location = self.location(record, key)
            location.mkdir(mode=0o700)
            copy_owned(Path(sources[key]), location / "incoming")
            sync_directory(location)
            sync_directory(location.parent)
        record["state"] = "ready"
        save_record(self.journal, record)
        return record

    def apply(self):
        record = self.read()
        if record["state"] != "ready":
            raise ValueError("Restore transaction is not ready")
        record["state"] = "installing"
        save_record(self.journal, record)
        for key, target in self.targets.items():
            location = self.location(record, key)
            if record["existed"][key]:
                os.rename(target, location / "previous")
                sync_directory(target.parent)
                sync_directory(location)
            os.rename(location / "incoming", target)
            sync_directory(target.parent)
            sync_directory(location)
        record["state"] = "installed"
        save_record(self.journal, record)
        return record

    def rollback(self):
        record = self.read()
        if record["state"] == "committed":
            raise ValueError("Committed restore needs a new rollback operation")
        if record["state"] == "rolled-back":
            return record
        record["state"] = "rolling-back"
        save_record(self.journal, record)
        for key, target in reversed(list(self.targets.items())):
            location = self.location(record, key)
            previous = location / "previous"
            if previous.exists():
                if target.exists():
                    os.rename(target, location / "rejected")
                    sync_directory(target.parent)
                    sync_directory(location)
                os.rename(previous, target)
                sync_directory(target.parent)
                sync_directory(location)
            elif not record["existed"][key] and not (location / "incoming").exists() and target.exists():
                os.rename(target, location / "rejected")
                sync_directory(target.parent)
                sync_directory(location)
        record["state"] = "rolled-back"
        save_record(self.journal, record)
        return record

    def commit(self):
        """Call only after restored service configuration and health are verified."""
        record = self.read()
        if record["state"] != "installed":
            raise ValueError("Restore transaction is not installed")
        record["state"] = "committed"
        save_record(self.journal, record)
        # Previous trees deliberately remain private and recoverable.
        return record
