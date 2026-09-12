"""Password-encrypted exports using GnuPG's AES256 + integrity-protected format."""
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def validate_passphrase(value):
    if not isinstance(value, str) or not 12 <= len(value) <= 1024 or any(c in value for c in "\r\n\x00"):
        raise ValueError("Backup passphrase must be 12–1024 characters without line breaks")
    return value


def transform(source, destination, passphrase, *, decrypt=False, max_bytes=1024 ** 4):
    validate_passphrase(passphrase)
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ValueError("Encryption destination already exists")
    with tempfile.TemporaryDirectory(prefix="elderbrain-crypto-", dir=destination.parent) as temp:
        work = Path(temp)
        output = work / "output"
        home = work / "gnupg"
        home.mkdir(mode=0o700)
        arguments = ["gpg", "--no-options", "--homedir", str(home), "--no-autostart", "--no-tty", "--batch",
                     "--pinentry-mode", "loopback", "--no-symkey-cache", "--passphrase-fd", "0", "--status-fd", "1",
                     "--output", str(output)]
        if decrypt:
            available = shutil.disk_usage(destination.parent).free - 1024 ** 3
            if available <= 0:
                raise ValueError("Insufficient free space for decryption")
            arguments += ["--max-output", str(min(max_bytes, available)), "--decrypt"]
        else:
            arguments += ["--cipher-algo", "AES256", "--s2k-mode", "3", "--s2k-digest-algo", "SHA256",
                          "--s2k-count", "65011712", "--compress-algo", "none", "--symmetric"]
        arguments += ["--", str(source)]
        result = subprocess.run(arguments, input=(passphrase + "\n").encode(), capture_output=True, timeout=24 * 3600)
        if result.returncode or (decrypt and b"[GNUPG:] GOODMDC" not in result.stdout):
            raise ValueError("Unable to decrypt or verify backup" if decrypt else "Unable to encrypt backup")
        os.chmod(output, 0o600)
        with output.open("rb") as data:
            os.fsync(data.fileno())
        # Publish only verified results, never partial plaintext from failed GPG.
        os.link(output, destination)
    return destination


@contextmanager
def decrypted(source, passphrase, *, parent=None, max_bytes=1024 ** 4):
    with tempfile.TemporaryDirectory(prefix="elderbrain-decrypted-", dir=parent) as temp:
        path = Path(temp) / "archive.tar.zst"
        transform(source, path, passphrase, decrypt=True, max_bytes=max_bytes)
        yield path
