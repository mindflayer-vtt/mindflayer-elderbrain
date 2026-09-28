"""Narrow local-kiosk capability for pre-login keyboard selection."""
import hmac
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import tempfile
import xml.etree.ElementTree as ET

RUNTIME = None  # Optional test override; PAM supplies /run/user/UID in production.
RULES = Path("/usr/share/X11/xkb/rules/evdev.xml")
SWAY_CONFIG = Path("/opt/mindflayer-elderbrain/sway.conf")


def layouts(rules=RULES):
    result = []
    for layout in ET.parse(rules).findall("./layoutList/layout"):
        name = layout.findtext("configItem/name", "")
        label = layout.findtext("configItem/description", name)
        for variant, description in [("", label)] + [
            (item.findtext("configItem/name", ""), item.findtext("configItem/description", ""))
            for item in layout.findall("variantList/variant")
        ]:
            if re.fullmatch(r"[a-z0-9_-]+", name) and re.fullmatch(r"[a-z0-9_-]*", variant):
                result.append({"value": name + ":" + variant, "label": description})
    return result


def operate(token, selected=None):
    if not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{64}", token):
        raise ValueError("Local kiosk required")
    uid = pwd.getpwnam("elderbrain-kiosk").pw_uid
    runtime = RUNTIME or Path(f"/run/user/{uid}")
    fd = os.open(runtime / "keyboard-token", os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_mode & 0o077:
            raise ValueError("Invalid kiosk capability file")
        if not hmac.compare_digest(stream.read(128).strip(), token):
            raise ValueError("Local kiosk required")
    choices = layouts()
    if selected is not None and selected not in {item["value"] for item in choices}:
        raise ValueError("Unsupported keyboard layout")
    sockets = [path for path in runtime.glob("sway-ipc.*.sock")
               if stat.S_ISSOCK(path.lstat().st_mode) and path.lstat().st_uid == uid]
    if len(sockets) != 1:
        raise ValueError("Kiosk is not available")
    command = ["runuser", "-u", "elderbrain-kiosk", "--", "swaymsg", "-s", str(sockets[0]), "-r"]
    if selected is not None:
        layout, variant = selected.split(":", 1)
        # All strings are validated against the installed XKB catalogue, no shell.
        response = subprocess.run(command + [f'input type:keyboard xkb_variant ""; input type:keyboard xkb_layout {layout}; input type:keyboard xkb_variant "{variant}"'],
                                  capture_output=True, text=True, check=True, timeout=5)
        if not all(item.get("success") for item in json.loads(response.stdout)):
            raise ValueError("Unable to apply keyboard layout")
    response = subprocess.run(command + ["-t", "get_inputs"], capture_output=True,
                              text=True, check=True, timeout=5)
    active = sorted({item.get("xkb_active_layout_name", "") for item in json.loads(response.stdout)
                     if item.get("type") == "keyboard"})
    return {"layouts": choices, "active": active}


def configured(config=SWAY_CONFIG):
    content = config.read_text()
    matches = re.findall(r"^input \* xkb_layout ([a-z0-9_-]+)$", content, re.M)
    variants = re.findall(r"^input \* xkb_variant ([a-z0-9_-]*)$", content, re.M)
    if len(matches) != 1 or len(variants) > 1:
        raise ValueError("Unsupported Sway keyboard configuration")
    return matches[0] + ":" + (variants[0] if variants else "")


def persistent(selected=None, config=SWAY_CONFIG):
    """Save an authenticated administrator choice in persistent Sway settings."""
    choices = layouts()
    if selected is not None and selected not in {item["value"] for item in choices}:
        raise ValueError("Unsupported keyboard layout")
    current = configured(config)
    if selected is not None and selected != current:
        target = config.resolve(strict=True)
        info = target.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
            raise ValueError("Unsafe Sway keyboard configuration")
        layout, variant = selected.split(":", 1)
        content = target.read_text()
        content = re.sub(r"^input \* xkb_layout [a-z0-9_-]+$", "input * xkb_layout " + layout, content, count=1, flags=re.M)
        content = re.sub(r"^input \* xkb_variant [a-z0-9_-]*\n", "", content, flags=re.M)
        if variant:
            content += "\ninput * xkb_variant " + variant + "\n"
        descriptor, temporary = tempfile.mkstemp(prefix=".sway-keyboard-", dir=target.parent)
        try:
            with os.fdopen(descriptor, "w") as stream:
                os.fchmod(stream.fileno(), info.st_mode & 0o777)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
        # Apply immediately if a kiosk session exists; the saved setting also
        # survives a restart even when the display is currently disconnected.
        try:
            uid = pwd.getpwnam("elderbrain-kiosk").pw_uid
            runtime = RUNTIME or Path(f"/run/user/{uid}")
            sockets = [path for path in runtime.glob("sway-ipc.*.sock") if stat.S_ISSOCK(path.lstat().st_mode) and path.lstat().st_uid == uid]
            if len(sockets) == 1:
                subprocess.run(["runuser", "-u", "elderbrain-kiosk", "--", "swaymsg", "-s", str(sockets[0]), "input", "type:keyboard", "xkb_layout", layout], check=True, timeout=5, capture_output=True)
                subprocess.run(["runuser", "-u", "elderbrain-kiosk", "--", "swaymsg", "-s", str(sockets[0]), "input", "type:keyboard", "xkb_variant", variant or '""'], check=True, timeout=5, capture_output=True)
        except (OSError, subprocess.SubprocessError):
            pass  # The persistent setting is applied when Sway next starts.
    return {"layouts": choices, "configured": configured(config)}
