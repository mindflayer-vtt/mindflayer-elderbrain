"""Bounded serial-install bundle verification. Never extract or execute untrusted files."""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tarfile
import tempfile

LIMIT = 4 * 1024 * 1024
IMAGES = {"rboot.bin": (0, 4096), "metadata-a.bin": (0x1000, 4096),
          "metadata-b.bin": (0x100000, 4096), "application.bin": (0x2000, 0xfe000)}
PAYLOAD = set(IMAGES) | {"install-rboot.py", "LICENSE"}
MEMBERS = PAYLOAD | {"manifest.json", "manifest.sig"}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate manifest key")
        result[key] = value
    return result


def verify(archive, public_key, *, expected_version=None):
    """Return verified bytes and metadata, using an externally pinned public key.

    Caller supplies the trust anchor from appliance installation, not the bundle.
    Hardware probing and image-format preflight remain mandatory before flashing.
    """
    fd = os.open(archive, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= LIMIT:
            raise ValueError("Invalid serial bundle file or size")
        compressed = stream.read(LIMIT + 1)
    if len(compressed) > LIMIT:
        raise ValueError("Serial bundle exceeds size limit")
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        expanded = stream.read(LIMIT + 1)
    if len(expanded) > LIMIT:
        raise ValueError("Expanded serial bundle exceeds size limit")
    files = {}
    with tarfile.open(fileobj=io.BytesIO(expanded), mode="r:") as contents:
        for entry in contents:
            if entry.name not in MEMBERS or entry.name in files or not entry.isfile():
                raise ValueError("Unexpected serial bundle member")
            maximum = IMAGES[entry.name][1] if entry.name in IMAGES else 128 * 1024
            if not 0 < entry.size <= maximum:
                raise ValueError("Invalid serial bundle member size")
            files[entry.name] = contents.extractfile(entry).read()
    if set(files) != MEMBERS:
        raise ValueError("Incomplete serial bundle")
    # Format 1 uses the firmware's RSA-2048/SHA-256 trust anchor. OpenSSL's
    # verifier ignores trailing signature bytes, so require the exact encoding.
    if len(files["manifest.sig"]) != 256:
        raise ValueError("Invalid serial bundle signature size")
    with tempfile.TemporaryDirectory(prefix="elderbrain-serial-verify-") as directory:
        root = Path(directory)
        (root / "manifest.json").write_bytes(files["manifest.json"])
        (root / "manifest.sig").write_bytes(files["manifest.sig"])
        result = subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(public_key),
                                 "-signature", str(root / "manifest.sig"), str(root / "manifest.json")],
                                capture_output=True, timeout=10, stdin=subprocess.DEVNULL)
        if result.returncode:
            raise ValueError("Serial bundle signature does not match the pinned signing key")
    manifest = json.loads(files["manifest.json"], object_pairs_hook=unique_object)
    if not isinstance(manifest, dict):
        raise ValueError("Invalid serial bundle manifest")
    for key, value in {"format": 1, "type": "mindflayer-serial-install", "hardware": "mindflayer-keypad-v1",
                       "chip": "esp8266", "flashSize": 0x400000, "deviceProtocol": 3, "preserveSectors": [0x3f9000, 0x3fa000]}.items():
        if type(manifest.get(key)) is not type(value) or manifest[key] != value:
            raise ValueError("Unsupported serial bundle target or layout")
    version = manifest.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?", version):
        raise ValueError("Invalid serial bundle version")
    if expected_version is not None and version != expected_version:
        raise ValueError("Serial bundle does not match the requested release")
    entries = manifest.get("files")
    if not isinstance(entries, list) or len(entries) != len(PAYLOAD):
        raise ValueError("Invalid serial manifest file list")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ValueError("Invalid serial manifest entry")
        name = entry["path"]
        if name not in PAYLOAD or name in seen:
            raise ValueError("Unexpected serial manifest file")
        seen.add(name)
        if type(entry.get("size")) is not int or entry["size"] != len(files[name]) or entry.get("sha256") != hashlib.sha256(files[name]).hexdigest():
            raise ValueError("Serial bundle file checksum or size mismatch")
        if name in IMAGES and (type(entry.get("address")) is not int or entry["address"] != IMAGES[name][0]):
            raise ValueError("Unsafe serial flash address")
    return manifest, {name: files[name] for name in PAYLOAD}
