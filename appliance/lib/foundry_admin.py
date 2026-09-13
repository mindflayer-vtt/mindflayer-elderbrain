"""Manage the recoverable Foundry administrator access key."""
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import stat


STATE = Path(os.environ.get("ELDERBRAIN_STATE_DIR", "/var/lib/mindflayer-elderbrain"))
WORDLIST = Path(os.environ.get("ELDERBRAIN_BOOTSTRAP_WORDS", "/opt/mindflayer-elderbrain/bootstrap-words.json"))
SECRET_KEYS = {"foundry_release_url", "foundry_username", "foundry_password", "foundry_admin_key"}


def _read_json(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {}
    if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
        raise ValueError("Unsafe Foundry secret file")
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or set(value) - SECRET_KEYS or any(not isinstance(item, str) for item in value.values()):
        raise ValueError("Invalid Foundry secret file")
    return value


def _words():
    words = json.loads(WORDLIST.read_text())
    if (not isinstance(words, list) or len(words) != 256 or len(set(words)) != 256
            or any(not isinstance(word, str) or not word.isascii() or not word.isalpha()
                   or not word.islower() or not 3 <= len(word) <= 8 for word in words)):
        raise ValueError("Invalid bootstrap word list")
    return words


def _generate():
    words = _words()
    return "-".join(secrets.choice(words) for _ in range(12))


def _valid(key):
    selected = key.split("-")
    allowed = set(_words())
    return len(selected) == 12 and all(word in allowed for word in selected)


def _write(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temporary, 1000, 1000)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _existing_admin_file():
    path = STATE / "foundry/Config/admin.txt"
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("Unsafe Foundry administrator file")
    return path


def _matches(path, key):
    if path.stat().st_size > 512:
        return False
    actual = path.read_text().strip()
    expected = hashlib.pbkdf2_hmac("sha512", key.encode(), b"17c4f39053ac5a50d5797c665ad1f4e6", 1000, 64).hex()
    return hmac.compare_digest(actual, expected)


def access_key(operation="status"):
    if operation not in ("status", "ensure", "reset"):
        raise ValueError("Invalid Foundry administrator operation")
    secret = STATE / "elderbrain/secrets/foundry-config.json"
    lock = secret.with_suffix(".lock")
    lock.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        value = _read_json(secret)
        key = value.get("foundry_admin_key")
        existing = _existing_admin_file()
        if key and operation != "reset":
            if not _valid(key):
                return {"managed": False, "resetRequired": True}
            if existing is not None and not _matches(existing, key):
                return {"managed": False, "resetRequired": True}
            return {"managed": True, "accessKey": key, "resetRequired": False}
        if operation == "status" or (operation == "ensure" and existing is not None):
            return {"managed": False, "resetRequired": existing is not None}
        key = _generate()
        _write(secret, {**value, "foundry_admin_key": key})
        if operation == "reset" and existing is not None:
            existing.unlink()
        return {"managed": True, "accessKey": key, "resetRequired": False}
    finally:
        os.close(descriptor)
