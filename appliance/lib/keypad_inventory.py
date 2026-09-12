"""Read-only projection of server registration; credentials never cross the bridge."""
import json
import os
from pathlib import Path
import re
import stat
import hashlib

MAX_BYTES = 4 * 1024 * 1024


def installation_receipts(state):
    """Project completed backup-covered journals, never the non-restored jobs list."""
    state = Path(state)
    def read(file):
        fd = os.open(file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("Invalid installation record")
            data = stream.read(65537)
        if len(data) > 65536:
            raise ValueError("Installation record exceeds limit")
        return json.loads(data)
    try:
        settings = read(state / "elderbrain/secrets/keypad-settings.json")
    except FileNotFoundError:
        return []
    latest = {}
    for directory in (state / "keypad-installations").iterdir() if (state / "keypad-installations").exists() else []:
        if not re.fullmatch(r"[a-f0-9]{32}", directory.name) or directory.is_symlink():
            continue
        try:
            journal = read(directory / "installation.json")
        except FileNotFoundError:
            continue
        result = journal.get("result")
        if journal.get("state") != "completed" or not isinstance(result, dict) or result.get("state") != "verified":
            continue
        identity, verified = result.get("deviceId"), result.get("configurationVerifiedAt")
        if (not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", identity) or
                type(verified) is not int or verified <= 0 or type(result.get("revision")) is not int or result["revision"] < 1 or
                not isinstance(result.get("configurationDigest"), str) or not re.fullmatch(r"[a-f0-9]{64}", result["configurationDigest"])):
            raise ValueError("Invalid completed installation receipt")
        receipt = {"installationId": directory.name, "deviceId": identity, "revision": result["revision"],
                   "hardware": result.get("hardware"), "firmware": result.get("firmware"),
                   "chipMac": result.get("chipMac"),
                   "configurationVerifiedAt": verified, "configurationDigest": result["configurationDigest"],
                   "matchesCurrentSettings": journal.get("settings") == settings,
                   "currentSettingsRevision": settings.get("revision")}
        if identity not in latest or verified > latest[identity]["configurationVerifiedAt"]:
            latest[identity] = receipt
    return list(latest.values())


def usb_serial_devices(sys_root=Path("/sys"), dev_root=Path("/dev")):
    """Passive discovery only: never open or reset a connected serial device."""
    sys_root, dev_root = Path(sys_root).resolve(), Path(dev_root)
    result = []
    for entry in sorted((sys_root / "class/tty").glob("tty*")):
        if not re.fullmatch(r"tty(?:USB|ACM)[0-9]+", entry.name):
            continue
        try:
            device = (entry / "device").resolve(strict=True)
            if not device.is_relative_to(sys_root):
                continue
            usb = device
            while usb != sys_root and not (usb / "idVendor").is_file():
                usb = usb.parent
            if usb == sys_root:
                continue
            def field(name):
                try:
                    with (usb / name).open() as data:
                        return "".join(c for c in data.read(256).strip() if c.isprintable())
                except FileNotFoundError:
                    return ""
            vendor, product = field("idVendor"), field("idProduct")
            if not all(re.fullmatch(r"[0-9a-fA-F]{4}", value) for value in (vendor, product)):
                continue
            node = dev_root / entry.name
            if not stat.S_ISCHR(node.stat().st_mode):
                continue
            result.append({"id": hashlib.sha256(str(device.relative_to(sys_root)).encode()).hexdigest()[:32],
                           "port": str(node), "vendorId": vendor.lower(), "productId": product.lower(),
                           "manufacturer": field("manufacturer"), "product": field("product"),
                           "serial": field("serial"), "chipVerified": False})
        except (OSError, RuntimeError):
            # Hot-unplug is normal during discovery. Do not present a stale target.
            continue
    return result


def registered_keypads(state):
    path = Path(state) / "mindflayer" / "devices.json"
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return []
    with os.fdopen(fd, "rb") as data:
        if not stat.S_ISREG(os.fstat(data.fileno()).st_mode):
            raise ValueError("Invalid registration store")
        raw = data.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Registration store exceeds limit")
    record = json.loads(raw)
    if not isinstance(record, dict) or record.get("version") != 1 or not isinstance(record.get("devices"), dict):
        raise ValueError("Unsupported registration store")
    identities = []
    for identity, device in record["devices"].items():
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", identity)
                or not isinstance(device, dict) or not isinstance(device.get("secret"), str)
                or not re.fullmatch(r"[0-9a-fA-F]{64}", device["secret"])):
            raise ValueError("Invalid registration store")
        identities.append(identity)
    return sorted(identities)
