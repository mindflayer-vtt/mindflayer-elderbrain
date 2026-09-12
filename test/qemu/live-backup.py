"""Live backup check exclusively for a disposable, installed appliance VM."""
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
    os.umask(0o077)
    state = Path("/var/lib/mindflayer-elderbrain")
    directory = state / "keypad-installations" / uuid.uuid4().hex
    directory.mkdir(mode=0o700)
    journal = directory / "installation.json"
    # Synthetic private material only; not a valid installation or credential.
    journal.write_text(json.dumps({"state": "backup-test", "canary": uuid.uuid4().hex}))
    with Path("/var/log/elderbrain-live-journal-canary.json").open("x") as output:
        json.dump({"path": str(journal), "sha256": hashlib.sha256(journal.read_bytes()).hexdigest()}, output)
    with open("/var/log/elderbrain-live-backup.json", "xb") as output, open("/var/log/elderbrain-live-backup.stderr", "xb") as errors:
        result = subprocess.run(["elderbrain", "backup"], stdout=output, stderr=errors, timeout=600)
    if result.returncode:
        raise SystemExit("Backup failed; inspect root-private /var/log/elderbrain-live-backup.stderr")
    result = json.loads(Path("/var/log/elderbrain-live-backup.json").read_text())
    sys.path.insert(0, "/opt/mindflayer-elderbrain")
    from backup_archive import ROOTS, validate
    manifest = validate(result["archive"])
    assert {entry["path"].split("/")[0] for entry in manifest["entries"]} == ROOTS
    entry = next(entry for entry in manifest["entries"] if entry["path"] == str(journal.relative_to(state)))
    assert entry["sha256"] == hashlib.sha256(journal.read_bytes()).hexdigest()
    assert entry["mode"] == 0o600
    print("Verified live backup contains every logical root and the private installation journal")


if __name__ == "__main__":
    main()
