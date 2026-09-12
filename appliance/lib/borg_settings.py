"""End-user Borg settings; never accept arbitrary borgmatic hooks or commands."""
import base64
import json
from pathlib import Path, PurePosixPath
import re
import secrets
import shlex

from backup_service import save_record


def bounded_number(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("Invalid " + label)
    return value


def host(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", value):
        raise ValueError("Use an IPv4 address or DNS hostname")
    return value


def directory(value, absolute):
    if (not isinstance(value, str) or not value or len(value) > 1024
            or not re.fullmatch(r"[A-Za-z0-9_./-]+", value)):
        raise ValueError("Invalid repository directory")
    path = PurePosixPath(value)
    if path.is_absolute() != absolute or ".." in path.parts or str(path) != value or value in ("/", "."):
        raise ValueError("Repository directory must be canonical and cannot be a filesystem root")
    if not absolute and value.startswith("-"):
        raise ValueError("Invalid relative repository directory")
    return value


class BorgSettings:
    def __init__(self, state):
        self.state = Path(state)
        self.directory = self.state / "elderbrain/secrets/borg"
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.file = self.directory / "settings.json"

    def read(self):
        if not self.file.exists():
            return None
        return json.loads(self.file.read_text())

    def public(self):
        settings = self.read()
        if settings is None:
            return {"configured": False}
        return {**{key: value for key, value in settings.items() if key != "passphrase"},
                "configured": True, "passphraseStored": True}

    def configure(self, data):
        if not isinstance(data, dict):
            raise ValueError("Settings must be an object")
        kind = data.get("kind")
        if kind not in ("nfs", "ssh"):
            raise ValueError("Select an NFS or Borg-over-SSH repository")
        if type(data.get("enabled", False)) is not bool:
            raise ValueError("Invalid schedule enable flag")
        schedule = data.get("schedule", "03:00")
        if not isinstance(schedule, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", schedule):
            raise ValueError("Schedule must be HH:MM in appliance local time")
        retention = data.get("retention", {"daily": 7, "weekly": 4, "monthly": 6})
        if not isinstance(retention, dict):
            raise ValueError("Invalid retention policy")
        retention = {key: bounded_number(retention.get(key), 1, 3650, "retention") for key in ("daily", "weekly", "monthly")}
        previous = self.read()
        passphrase = data.get("passphrase") or (previous or {}).get("passphrase") or secrets.token_urlsafe(32)
        if not isinstance(passphrase, str) or not 12 <= len(passphrase) <= 1024 or any(c in passphrase for c in "\r\n\x00"):
            raise ValueError("Repository passphrase must be 12–1024 characters without line breaks")
        settings = {"format": 1, "kind": kind, "enabled": data.get("enabled", False),
                    "schedule": schedule, "retention": retention, "passphrase": passphrase,
                    "host": host(data.get("host"))}
        if kind == "nfs":
            settings.update(export=directory(data.get("export"), True), repository=directory(data.get("repository", "elderbrain"), False))
        else:
            user = data.get("user")
            if not isinstance(user, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}", user):
                raise ValueError("Invalid SSH user")
            key = data.get("hostKey", "")
            if not isinstance(key, str) or not re.fullmatch(r"(?:ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256) [A-Za-z0-9+/]+=*", key):
                raise ValueError("Provide the verified SSH host public key (type and base64 data)")
            try:
                if len(base64.b64decode(key.split()[1], validate=True)) < 16:
                    raise ValueError("SSH host key is too short")
            except Exception as error:
                raise ValueError("Invalid SSH host public key") from error
            settings.update(user=user, port=bounded_number(data.get("port", 22), 1, 65535, "SSH port"),
                            repository=directory(data.get("repository"), True), hostKey=key)
        save_record(self.file, settings)
        return self.public()

    def render(self, settings, identity, version="unknown"):
        if not re.fullmatch(r"[a-zA-Z0-9-]{1,64}", identity):
            raise ValueError("Invalid appliance identity")
        if not re.fullmatch(r"[A-Za-z0-9.+-]{1,64}", version) or "--" in version or "--" in identity:
            raise ValueError("Invalid appliance version or identity")
        repository = ("/mnt/elderbrain-backup/" + settings["repository"] if settings["kind"] == "nfs" else
                      f'ssh://{settings["user"]}@{settings["host"]}:{settings["port"]}{settings["repository"]}')
        config = {"source_directories": ["appliance.tar.zst", "metadata.json"],
                  "working_directory": str(self.state / "borg-staging"),
                  "repositories": [{"path": repository, "label": "elderbrain"}],
                  "encryption_passphrase": settings["passphrase"], "compression": "none",
                  "archive_name_format": "elderbrain-" + identity + "--" + version + "--{now:%Y-%m-%dT%H:%M:%S.%f}",
                  # Retain/prune this appliance across software versions, never
                  # another appliance sharing the repository. Restore listing
                  # explicitly overrides this filter to enable replacement recovery.
                  "match_archives": "sh:elderbrain-" + identity + "--*",
                  "keep_daily": settings["retention"]["daily"], "keep_weekly": settings["retention"]["weekly"],
                  "keep_monthly": settings["retention"]["monthly"],
                  "ssh_command": shlex.join(["ssh", "-oBatchMode=yes", "-oStrictHostKeyChecking=yes",
                                             "-oIdentitiesOnly=yes", "-oConnectTimeout=20", "-oServerAliveInterval=15",
                                             "-oServerAliveCountMax=3", "-oUserKnownHostsFile=" + str(self.directory / "known_hosts"),
                                             "-i", str(self.directory / "id_ed25519")])}
        return config

    def timer(self):
        settings = self.read()
        if settings is None:
            raise ValueError("Backup destination is not configured")
        return ("[Unit]\nDescription=Scheduled Elderbrain backup\n\n[Timer]\n"
                f'OnCalendar=*-*-* {settings["schedule"]}:00\n'
                "Persistent=true\nRandomizedDelaySec=300\nUnit=elderbrain-backup.service\n\n[Install]\nWantedBy=timers.target\n")
