"""Narrow local-kiosk capability for pre-login keyboard selection."""
import hmac
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import xml.etree.ElementTree as ET

RUNTIME = None  # Optional test override; PAM supplies /run/user/UID in production.
RULES = Path("/usr/share/X11/xkb/rules/evdev.xml")


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
