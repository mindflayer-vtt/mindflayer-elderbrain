"""Versioned, secret-bearing backup archives. Callers must quiesce services first.

Validation never extracts archive paths. Restore orchestration owns maintenance,
rollback and mapping the logical roots onto their fixed appliance destinations.
"""
import hashlib
import json
import os
import shutil
from contextlib import contextmanager
from collections import deque
from pathlib import Path, PurePosixPath
import stat
import subprocess
import tarfile
import tempfile
import time
from datetime import datetime, timezone

FORMAT = 1
ROOTS = {"foundry", "elderbrain", "mindflayer", "traefik", "firmware",
         "service-config", "ssh-root", "ssh-admin", "ssh-server", "admin-ca",
         "browser", "keypad-installations"}
MAX_MANIFEST = 32 * 1024 * 1024


class LimitedReader:
    """Count every decompressed byte, including tar padding and PAX headers."""
    def __init__(self, stream, limit):
        self.stream, self.remaining = stream, limit

    def read(self, size=-1):
        size = min(size if size >= 0 else self.remaining + 1, self.remaining + 1)
        data = self.stream.read(size)
        self.remaining -= len(data)
        if self.remaining < 0:
            raise ValueError("Archive exceeds restore limits")
        return data


def remaining(deadline):
    if deadline is None:
        return None
    value = deadline - time.monotonic()
    if value <= 0:
        raise TimeoutError("Backup attempt exceeded its configured time limit")
    return value


def digest(stream, *, deadline=None):
    value = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        remaining(deadline)
        value.update(chunk)
    return value.hexdigest()


def safe_name(name):
    p = PurePosixPath(name)
    if (not name or p.is_absolute() or str(p) != name or
            any(part in (".", "..") for part in p.parts) or
            p.parts[0] not in ROOTS or "\x00" in name):
        raise ValueError("Unsafe or unsupported archive path")
    return p


# Fixed OS-managed file links, never caller-controlled targets or directories.
SYSTEM_FILE_LINKS = {
    "ssh-server/ssh_config.d/20-systemd-ssh-proxy.conf":
        "/usr/lib/systemd/ssh_config.d/20-systemd-ssh-proxy.conf",
}


def safe_link(name, target):
    if SYSTEM_FILE_LINKS.get(name) == target:
        return
    if not target or PurePosixPath(target).is_absolute() or "\x00" in target:
        raise ValueError("Absolute or empty symbolic link is not supported")
    parts = list(PurePosixPath(name).parent.parts)
    for part in PurePosixPath(target).parts:
        if part == "..":
            if len(parts) <= 1:
                raise ValueError("Symbolic link escapes its backup root")
            parts.pop()
        elif part != ".":
            parts.append(part)


def validate_link_graph(entries):
    links = {e["path"]: e["target"] for e in entries if e["type"] == "symlink"}
    for name, target in links.items():
        if SYSTEM_FILE_LINKS.get(name) == target:
            continue
        resolved = list(PurePosixPath(name).parent.parts)
        pending = deque(PurePosixPath(target).parts)
        expansions = 0
        while pending:
            part = pending.popleft()
            if part == "..":
                if len(resolved) <= 1:
                    raise ValueError("Symbolic link chain escapes its backup root")
                resolved.pop()
            elif part != ".":
                candidate = "/".join([*resolved, part])
                if candidate in links:
                    if SYSTEM_FILE_LINKS.get(candidate) == links[candidate]:
                        if pending:
                            raise ValueError("Symbolic link traverses an external system file")
                        break
                    expansions += 1
                    if expansions > 40:
                        raise ValueError("Symbolic link cycle or excessive depth")
                    pending.extendleft(reversed(PurePosixPath(links[candidate]).parts))
                else:
                    resolved.append(part)


def create(destination, sources, *, version, identity, deadline=None):
    """sources maps logical roots to paths; no missing requested roots are ignored."""
    if not sources or not set(sources) <= ROOTS:
        raise ValueError("Unsupported backup roots")
    destination = Path(destination)
    if destination.exists():
        raise ValueError("Backup destination already exists")
    for root in sources.values():
        root = Path(root)
        if root.is_symlink() or not root.is_dir():
            raise ValueError("Backup root must be an existing directory")
        if destination.resolve().is_relative_to(root.resolve()):
            raise ValueError("Backup destination cannot be inside a source")
    manifest = {"format": FORMAT, "applianceVersion": version,
                "applianceIdentity": identity,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "containsSecrets": True, "roots": sorted(sources), "entries": []}
    with tempfile.TemporaryDirectory(prefix="elderbrain-backup-", dir=destination.parent) as work:
        plain = Path(work) / "archive.tar"
        with tarfile.open(plain, "w", format=tarfile.PAX_FORMAT) as archive:
            for logical, source in sorted(sources.items()):
                source = Path(source)
                for path in [source, *sorted(source.rglob("*"))]:
                    remaining(deadline)
                    name = logical if path == source else logical + "/" + path.relative_to(source).as_posix()
                    safe_name(name)
                    # Store hard-linked files independently; never create tar hardlinks.
                    archive.inodes.clear()
                    info = archive.gettarinfo(str(path), arcname=name)
                    info.mode &= 0o7777
                    if info.mode & (stat.S_ISUID | stat.S_ISGID):
                        raise ValueError("Set-ID permissions are not accepted")
                    entry = {"path": name, "mode": info.mode, "uid": info.uid,
                             "gid": info.gid, "mtime": info.mtime, "size": info.size}
                    if info.isfile():
                        entry["type"] = "file"
                        with path.open("rb") as data:
                            entry["sha256"] = digest(data, deadline=deadline)
                            data.seek(0)
                            archive.addfile(info, data)
                    elif info.isdir():
                        entry["type"] = "directory"
                        archive.addfile(info)
                    elif info.issym():
                        safe_link(name, info.linkname)
                        entry.update(type="symlink", target=info.linkname)
                        archive.addfile(info)
                    else:
                        raise ValueError("Backup contains unsupported special file: " + name)
                    manifest["entries"].append(entry)
            validate_link_graph(manifest["entries"])
            encoded = json.dumps(manifest, sort_keys=True).encode()
            if len(encoded) > MAX_MANIFEST:
                raise ValueError("Backup manifest exceeds supported size")
            import io
            info = tarfile.TarInfo("manifest.json")
            info.size, info.mode = len(encoded), 0o600
            archive.addfile(info, io.BytesIO(encoded))
        compressed = Path(work) / "archive.tar.zst"
        subprocess.run(["zstd", "-q", "-T2", str(plain), "-o", str(compressed)], check=True,
                       timeout=remaining(deadline))
        os.chmod(compressed, 0o600)
        # Detect files changing between hashing and reading, before publication.
        validate(compressed, deadline=deadline)
        # Publish without overwriting any existing archive, including a raced symlink.
        os.link(compressed, destination)
    return manifest


def validate(filename, *, max_bytes=1024 ** 4, deadline=None):
    """Stream validation with a decompressed-size bound; no untrusted extraction."""
    seen = {}
    manifest = None
    consumed = 0
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(["zstd", "-q", "-d", "-c", "--", str(filename)],
                                   stdout=subprocess.PIPE, stderr=errors)
        try:
            reader = LimitedReader(process.stdout, max_bytes)
            with tarfile.open(fileobj=reader, mode="r|") as archive:
                for info in archive:
                    remaining(deadline)
                    consumed += info.size + 512
                    if consumed > max_bytes or len(seen) > 1000000:
                        raise ValueError("Archive exceeds restore limits")
                    if info.name == "manifest.json":
                        if manifest is not None or not info.isfile() or info.size > MAX_MANIFEST:
                            raise ValueError("Invalid or duplicate manifest")
                        manifest = json.load(archive.extractfile(info))
                        continue
                    safe_name(info.name)
                    if info.name in seen:
                        raise ValueError("Duplicate archive path")
                    if info.uid < 0 or info.gid < 0 or not 0 <= info.mode <= 0o7777 or info.size < 0:
                        raise ValueError("Invalid file metadata")
                    entry = {"path": info.name, "mode": info.mode, "uid": info.uid,
                             "gid": info.gid, "mtime": info.mtime, "size": info.size}
                    if info.isfile():
                        entry.update(type="file", sha256=digest(archive.extractfile(info), deadline=deadline))
                    elif info.isdir():
                        entry["type"] = "directory"
                    elif info.issym():
                        safe_link(info.name, info.linkname)
                        entry.update(type="symlink", target=info.linkname)
                    else:
                        raise ValueError("Unsupported archive member")
                    if info.mode & (stat.S_ISUID | stat.S_ISGID):
                        raise ValueError("Set-ID permissions are not accepted")
                    seen[info.name] = entry
            # Drain to detect truncated/corrupted zstd frames after tar end markers.
            while chunk := reader.read(1024 * 1024):
                remaining(deadline)
                consumed += len(chunk)
                if consumed > max_bytes:
                    raise ValueError("Archive exceeds restore limits")
            if process.wait() != 0:
                raise ValueError("Invalid zstd archive")
        finally:
            process.stdout.close()
            if process.poll() is None:
                process.kill()
            process.wait()
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise ValueError("Unsupported backup format")
    if (any(not isinstance(manifest.get(key), str) or not manifest[key] or len(manifest[key]) > 256
            for key in ("applianceVersion", "applianceIdentity", "createdAt"))
            or manifest.get("containsSecrets") is not True):
        raise ValueError("Invalid backup compatibility metadata")
    try:
        stamp = datetime.fromisoformat(manifest["createdAt"])
        if stamp.tzinfo is None:
            raise ValueError("Missing timezone")
    except ValueError as error:
        raise ValueError("Invalid backup timestamp") from error
    entries = manifest.get("entries")
    if not isinstance(entries, list) or entries != list(seen.values()):
        raise ValueError("Archive contents or checksums do not match manifest")
    roots = manifest.get("roots")
    if (not isinstance(roots, list) or not roots or any(not isinstance(root, str) for root in roots)
            or len(set(roots)) != len(roots) or set(roots) != {p.split('/')[0] for p in seen}
            or any(seen.get(root, {}).get("type") != "directory" for root in roots)):
        raise ValueError("Invalid backup root manifest")
    for name in seen:
        for parent in PurePosixPath(name).parents:
            if str(parent) != "." and seen.get(str(parent), {}).get("type") != "directory":
                raise ValueError("Archive member has a non-directory parent")
    validate_link_graph(entries)
    return manifest


def preview(manifest):
    """Only metadata, never file contents or secrets, is returned to the UI."""
    return {key: manifest[key] for key in
            ("format", "applianceVersion", "applianceIdentity", "createdAt", "containsSecrets", "roots")} | {
        "files": sum(e["type"] == "file" for e in manifest["entries"]),
        "bytes": sum(e["size"] for e in manifest["entries"]),
    }


@contextmanager
def stage(filename, *, parent=None, max_bytes=1024 ** 4, restore_ownership=True):
    """Yield (private staging directory, manifest), never mutate live state.

    Snapshot first to prevent upload replacement between validation and extraction.
    All files are created exclusively; links are created last. Callers must keep
    staging on a trusted filesystem and retain rollback data before installation.
    """
    with tempfile.TemporaryDirectory(prefix="elderbrain-restore-", dir=parent) as work:
        work = Path(work)
        snapshot = work / "input.tar.zst"
        with open(filename, "rb") as source, snapshot.open("xb") as target:
            os.chmod(snapshot, 0o600)
            copied = 0
            while chunk := source.read(1024 * 1024):
                copied += len(chunk)
                if copied > max_bytes:
                    raise ValueError("Compressed archive exceeds restore limits")
                target.write(chunk)
        manifest = validate(snapshot, max_bytes=max_bytes)
        output = work / "contents"
        output.mkdir(mode=0o700)
        entries = manifest["entries"]
        for entry in sorted(entries, key=lambda e: len(PurePosixPath(e["path"]).parts)):
            if entry["type"] == "directory":
                (output / entry["path"]).mkdir(mode=0o700)
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(["zstd", "-q", "-d", "-c", "--", str(snapshot)],
                                       stdout=subprocess.PIPE, stderr=errors)
            try:
                with tarfile.open(fileobj=LimitedReader(process.stdout, max_bytes), mode="r|") as archive:
                    for info in archive:
                        if info.name == "manifest.json" or not info.isfile():
                            continue
                        target = output / info.name
                        with target.open("xb") as data:
                            os.chmod(target, 0o600)
                            shutil.copyfileobj(archive.extractfile(info), data, 1024 * 1024)
                while process.stdout.read(1024 * 1024):
                    pass
                if process.wait() != 0:
                    raise ValueError("Archive decompression failed")
            finally:
                process.stdout.close()
                if process.poll() is None:
                    process.kill()
                process.wait()
        for entry in entries:
            if entry["type"] == "symlink":
                (output / entry["path"]).symlink_to(entry["target"])
        # Set directory metadata last so restrictive modes do not impede staging.
        for entry in sorted(entries, key=lambda e: len(PurePosixPath(e["path"]).parts), reverse=True):
            target = output / entry["path"]
            if restore_ownership:
                info = target.lstat()
                if (info.st_uid, info.st_gid) != (entry["uid"], entry["gid"]):
                    os.chown(target, entry["uid"], entry["gid"], follow_symlinks=False)
            if entry["type"] != "symlink":
                os.chmod(target, entry["mode"])
            os.utime(target, (entry["mtime"], entry["mtime"]), follow_symlinks=False)
        yield output, manifest
