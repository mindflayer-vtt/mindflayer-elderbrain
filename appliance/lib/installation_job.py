"""Installation sequencing and private recovery journal.

The worker supplies a backend for verified artifacts, serial access and the
private container commands. Progress/result values are safe for the jobs API;
the journal and prepared envelope are not.
"""
import base64
import hashlib
from pathlib import Path
import re
import time
import zlib

from backup_service import save_record


def admission(source, state):
    import os
    import stat
    import json
    from serial_release import version_string
    if (not isinstance(source, dict) or not isinstance(source.get("usbId"), str) or
            not re.fullmatch(r"[a-f0-9]{32}", source["usbId"]) or type(source.get("adopt", False)) is not bool):
        raise ValueError("Invalid installation request")
    request = {"usbId": source["usbId"], "version": version_string(source.get("version")), "adopt": source.get("adopt", False)}
    fd = os.open(Path(state) / "elderbrain/secrets/keypad-settings.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("Invalid keypad settings file")
        data = stream.read(16385)
    if len(data) > 16384:
        raise ValueError("Keypad settings exceed limit")
    settings = json.loads(data)
    if (not isinstance(settings, dict) or type(settings.get("revision")) is not int or settings["revision"] < 1 or
            type(source.get("revision")) is not int or source["revision"] != settings["revision"]):
        raise ValueError("Keypad settings changed; refresh before installation")
    for name, minimum, maximum in (("ssid", 1, 32), ("psk", 8, 63), ("serverHost", 1, 253)):
        value = settings.get(name)
        if not isinstance(value, str) or "\0" in value or not minimum <= len(value.encode()) <= maximum:
            raise ValueError("Invalid central keypad settings")
    if type(settings.get("serverPort")) is not int or not 1 <= settings["serverPort"] <= 65535:
        raise ValueError("Invalid central keypad port")
    return request, settings


def validate_plan(plan):
    if not isinstance(plan, dict) or plan.get("action") not in ("initial", "preserve", "adopt"):
        raise ValueError("Invalid installation plan")
    identity = plan.get("deviceId")
    if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", identity):
        raise ValueError("Invalid prepared identity")
    encoded = plan.get("envelope")
    if not isinstance(encoded, str) or len(encoded) > 1380:
        raise ValueError("Invalid provisioning envelope")
    envelope = base64.b64decode(encoded, validate=True)
    if (not 12 <= len(envelope) <= 1035 or envelope[:5] != b"MFP1\x01" or
            int.from_bytes(envelope[5:7], "big") != len(envelope) - 11 or
            int.from_bytes(envelope[-4:], "big") != zlib.crc32(envelope[:-4]) or
            plan.get("configurationDigest") != hashlib.sha256(envelope).hexdigest()):
        raise ValueError("Prepared envelope checksum or digest mismatch")
    credential = plan.get("newCredential")
    if plan["action"] == "preserve":
        if credential is not None:
            raise ValueError("Preserved identity must not replace credentials")
    elif (not isinstance(credential, dict) or credential.get("id") != identity or
          not isinstance(credential.get("secret"), str) or not re.fullmatch(r"[a-f0-9]{64}", credential["secret"])):
        raise ValueError("Invalid prepared credential")
    return envelope


def run_installation(directory, request, settings, backend, progress):
    """Run under the persistent host-job lock; do not auto-retry failed flashing."""
    if (not isinstance(request, dict) or not isinstance(request.get("usbId"), str) or
            not re.fullmatch(r"[a-f0-9]{32}", request["usbId"]) or
            not isinstance(request.get("version"), str) or
            not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?", request["version"]) or
            type(request.get("adopt", False)) is not bool):
        raise ValueError("Invalid installation request")
    if not isinstance(settings, dict) or type(settings.get("revision")) is not int or settings["revision"] < 1:
        raise ValueError("Save central keypad settings before installation")
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    journal_path = directory / "installation.json"
    journal = {"state": "running", "request": dict(request), "settings": dict(settings)}

    def stage(name):
        journal["stage"] = name
        save_record(journal_path, journal)
        progress({"stage": name})

    try:
        stage("preflight")
        serial = backend.preflight(request, directory)
        stage("backup-provisioning")
        sector_a, sector_b = serial.backup()
        chip_mac = serial.mac
        if not isinstance(chip_mac, str) or not re.fullmatch(r"[a-f0-9]{2}(?::[a-f0-9]{2}){5}", chip_mac):
            raise ValueError("Keypad hardware identity was not verified")
        journal["chipMac"] = chip_mac
        stage("prepare-provisioning")
        plan = backend.prepare(sector_a, sector_b, settings, request.get("adopt", False))
        envelope = validate_plan(plan)
        if plan["action"] == "adopt" and request.get("adopt") is not True:
            raise ValueError("Foreign keypad adoption requires explicit consent")
        # Persist the exact credential/envelope before any registration or flash.
        journal["plan"] = plan
        stage("register-credential")
        if plan["newCredential"] is not None:
            backend.register(plan["newCredential"])
        stage("flash-firmware")
        serial.flash()
        stage("serial-provisioning")
        journal["provisioningStartedAt"] = int(time.time() * 1000)
        save_record(journal_path, journal)
        backend.provision(serial, envelope)
        stage("verify-online")
        observed = backend.verify_online(plan["deviceId"], request["version"], plan["configurationDigest"], journal["provisioningStartedAt"])
        if (not isinstance(observed, dict) or observed.get("id") != plan["deviceId"] or
                observed.get("connected") is not True or observed.get("deviceAuthenticated") is not True or
                observed.get("hardware") != "mindflayer-keypad-v1" or observed.get("firmware") != request["version"] or
                observed.get("configurationDigest") != plan["configurationDigest"] or
                type(observed.get("configurationVerifiedAt")) is not int or
                not journal["provisioningStartedAt"] <= observed["configurationVerifiedAt"] <= int(time.time() * 1000) + 5000):
            raise ValueError("Authenticated online configuration was not confirmed")
        result = {"state": "verified", "deviceId": plan["deviceId"], "revision": settings["revision"],
                  "chipMac": chip_mac,
                  "firmware": request["version"], "hardware": observed["hardware"],
                  "configurationVerifiedAt": observed["configurationVerifiedAt"],
                  "configurationDigest": plan["configurationDigest"]}
        journal.update(state="completed", result=result)
        stage("completed")
        return result
    except Exception as error:
        journal.update(state="failed", error=str(error))
        save_record(journal_path, journal)
        raise RuntimeError("Installation stopped at " + journal["stage"] +
                           "; retain this job's provisioning backups and private recovery journal before retrying") from None
