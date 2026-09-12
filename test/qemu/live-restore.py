"""Destructive restore smoke test, exclusively for a disposable installed VM."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid


def main():
    if sys.argv[1:] != ["--confirm-disposable-vm"]:
        raise SystemExit("Requires --confirm-disposable-vm; never use on a real appliance")
    subprocess.run(["systemd-detect-virt", "--vm", "--quiet"], check=True)
    state = Path("/var/lib/mindflayer-elderbrain")
    archive = Path(json.loads(Path("/var/log/elderbrain-live-backup.json").read_text())["archive"])
    if archive.parent != state / "backups" or not archive.is_file():
        raise SystemExit("Expected the previously verified local test backup")
    # These files must retain their bytes; never print their contents or digests.
    preserved = [state / "elderbrain/secrets/admin.json", Path("/root/.ssh/authorized_keys")]
    hashes = {path: hashlib.sha256(path.read_bytes()).digest() for path in preserved}
    canary = json.loads(Path("/var/log/elderbrain-live-journal-canary.json").read_text())
    journal = Path(canary["path"])
    if journal.parent.parent != state / "keypad-installations" or journal.name != "installation.json":
        raise SystemExit("Unexpected test journal path")
    journal.write_text(json.dumps({"state": "backup-test", "changed": True}))
    marker = state / "elderbrain" / ("restore-test-" + uuid.uuid4().hex)
    fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as data:
        data.write("This post-backup disposable test file must only survive in rollback.\n")
    os.umask(0o077)
    with open("/var/log/elderbrain-live-restore.json", "xb") as output, open("/var/log/elderbrain-live-restore.stderr", "xb") as errors:
        result = subprocess.run(["elderbrain", "restore", str(archive), "--confirm-restore"],
                                stdout=output, stderr=errors, timeout=600)
    if result.returncode:
        raise SystemExit("Restore failed; inspect root-private /var/log/elderbrain-live-restore.stderr")
    result = json.loads(Path("/var/log/elderbrain-live-restore.json").read_text())
    assert result["state"] == "completed", "Restore did not complete"
    assert not marker.exists(), "Restore did not replace live configuration"
    assert all(hashlib.sha256(path.read_bytes()).digest() == digest for path, digest in hashes.items()), "Credential bytes changed"
    assert hashlib.sha256(journal.read_bytes()).hexdigest() == canary["sha256"], "Installation journal was not restored"
    assert journal.stat().st_mode & 0o777 == 0o600, "Installation journal permissions changed"
    sys.path.insert(0, "/opt/mindflayer-elderbrain")
    from backup_archive import validate
    rollback = validate(result["rollbackArchive"])
    assert any(entry["path"] == "elderbrain/" + marker.name for entry in rollback["entries"]), "Rollback omitted post-backup data"
    assert os.readlink("/etc/ssh/ssh_config.d/20-systemd-ssh-proxy.conf") == "/usr/lib/systemd/ssh_config.d/20-systemd-ssh-proxy.conf"
    print("Verified live restore, credential preservation, system SSH link and rollback capture")


if __name__ == "__main__":
    main()
