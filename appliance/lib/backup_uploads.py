"""Private, bounded uploads. Immutable IDs are used instead of caller paths."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
import uuid

from backup_service import save_record


class UploadStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)

    def path(self, identity):
        if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{32}", identity):
            raise ValueError("Invalid upload identity")
        return self.directory / (identity + ".tar.zst")

    def receive(self, stream, size, *, max_bytes=1024 ** 4, reserve_bytes=1024 ** 3):
        if type(size) is not int or not 0 < size <= max_bytes:
            raise ValueError("Invalid upload size")
        gate = os.open(self.directory / "upload.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(gate, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError("Another upload is running") from error
            if size + reserve_bytes > shutil.disk_usage(self.directory).free:
                raise ValueError("Insufficient disk space for upload")
            identity = uuid.uuid4().hex
            destination = self.path(identity)
            partial = destination.with_suffix(".partial")
            digest = hashlib.sha256()
            remaining = size
            try:
                fd = os.open(partial, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "wb") as output:
                    while remaining:
                        chunk = stream.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise ValueError("Truncated backup upload")
                        remaining -= len(chunk)
                        digest.update(chunk)
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                os.link(partial, destination)
                record = {"id": identity, "size": size, "sha256": digest.hexdigest(), "createdAt": time.time()}
                save_record(destination.with_suffix(".json"), record)
                return record
            finally:
                partial.unlink(missing_ok=True)
        finally:
            os.close(gate)

    def verify(self, identity, expected=None):
        path = self.path(identity)
        record = json.loads(path.with_suffix(".json").read_text())
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        digest = hashlib.sha256()
        size = 0
        with os.fdopen(fd, "rb") as data:
            while chunk := data.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        if size != record["size"] or digest.hexdigest() != record["sha256"] or (expected and digest.hexdigest() != expected):
            raise ValueError("Uploaded backup changed since validation")
        return path, record["sha256"]
