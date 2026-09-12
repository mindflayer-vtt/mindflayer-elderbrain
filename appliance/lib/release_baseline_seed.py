"""Finalize a trusted ISO installation into an immutable update baseline."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

# The stable launcher executes this file with isolated Python startup from the
# independently retained recovery tree, not from the replaceable live runtime.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from appliance_release import unique
from backup_service import Maintenance, save_record
from release_baseline import prepare
from release_baseline_install import Migration
from release_bootstrap import active_generation, verify_active
from release_policy import ReleasePolicy
from release_recovery import health
from release_runtime import read_regular
from release_services import UpdateServices


METADATA_FIELDS = {"format", "version", "releaseSequence", "sourceCommit", "sourceTree",
                   "inputMode", "sourceIdentity"}


def install_metadata(path):
    path = Path(path).absolute()
    info = path.lstat()
    if (path.resolve() != path or not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o644):
        raise ValueError("Install baseline metadata must be a canonical root-owned file")
    raw = read_regular(path, 65536)
    value = json.loads(raw, object_pairs_hook=unique)
    if (not isinstance(value, dict) or set(value) != METADATA_FIELDS
            or type(value["format"]) is not int or value["format"] != 1
            or not isinstance(value["version"], str)
            or not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", value["version"])
            or type(value["releaseSequence"]) is not int
            or not 1 <= value["releaseSequence"] <= 2 ** 63 - 1
            or any(not isinstance(value[name], str) or not re.fullmatch(r"[a-f0-9]{40}", value[name])
                   for name in ("sourceCommit", "sourceTree"))
            or value["inputMode"] not in ("tracked-commit", "development-worktree")
            or not isinstance(value["sourceIdentity"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", value["sourceIdentity"])):
        raise ValueError("Invalid install baseline metadata")
    core = {key: value[key] for key in value if key != "sourceIdentity"}
    encoded = json.dumps(core, sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(encoded).hexdigest() != value["sourceIdentity"]:
        raise ValueError("Install baseline source identity does not match metadata")
    return value, hashlib.sha256(raw).hexdigest()


def expected_policy(metadata, digest):
    return {"format": 1, "highestSequence": metadata["releaseSequence"],
            "version": metadata["version"], "manifestSha256": digest}


def complete_receipt(path, metadata, digest):
    path = Path(path)
    if not path.exists():
        return None
    info = path.lstat()
    if (path.resolve() != path.absolute() or not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600):
        raise ValueError("Install baseline receipt must be private and canonical")
    value = json.loads(read_regular(path, 4096), object_pairs_hook=unique)
    expected = {"format": 1, "state": "completed", "sourceIdentity": metadata["sourceIdentity"],
                "releaseSequence": metadata["releaseSequence"], "version": metadata["version"],
                "manifestSha256": digest}
    if value != expected:
        raise ValueError("Install baseline receipt does not match this OS installation")
    return value


def finalize(*, host_root=Path("/"), run=None):
    root = Path(host_root).absolute()
    state, runtime = root / "var/lib/mindflayer-elderbrain", root / "opt/mindflayer-elderbrain"
    metadata, digest = install_metadata(root / "etc/elderbrain/install-baseline.json")
    receipt_path = root / "etc/elderbrain/install-baseline-complete.json"
    receipt = complete_receipt(receipt_path, metadata, digest)
    policy = ReleasePolicy(state)
    if receipt is not None:
        expected, current = expected_policy(metadata, digest), policy.current()
        if (current.get("highestSequence", 0) < expected["highestSequence"]
                or (current["highestSequence"] == expected["highestSequence"]
                    and current != expected)):
            raise ValueError("Completed install baseline conflicts with release policy")
        return receipt
    if (runtime / "VERSION").read_text().strip() != metadata["version"]:
        raise ValueError("Installed runtime version differs from baseline metadata")

    directory = state / "release-baselines"
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if (directory.resolve() != directory or info.st_uid != os.geteuid()
            or not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077):
        raise ValueError("Install baseline staging must be private")
    options = {} if run is None else {"run": run}
    prepared = prepare(runtime, state=state, directory=directory, host_root=root, **options)
    services = UpdateServices(runtime, health_check=lambda saved: health(
        saved, state, management_socket=root / "run/elderbrain/management.sock"))
    maintenance = Maintenance(state / "maintenance", services)

    def recovery_ready():
        generation = active_generation(directory=root / "usr/lib/elderbrain-recovery")
        verify_active(generation["bundle"], generation["recoveryApi"], host_root=root)

    migration_options = {} if run is None else {"run": run}
    migrated = Migration(maintenance, host_root=root).install(
        Path(prepared["directory"]), runtime / "baseline-stack.service",
        require_bootstrap=recovery_ready, **migration_options)
    if migrated["state"] != "completed":
        raise RuntimeError("Install baseline migration did not complete")
    policy.install_baseline({"releaseSequence": metadata["releaseSequence"],
                             "version": metadata["version"], "manifestSha256": digest})
    receipt = {"format": 1, "state": "completed", "sourceIdentity": metadata["sourceIdentity"],
               "releaseSequence": metadata["releaseSequence"], "version": metadata["version"],
               "manifestSha256": digest}
    save_record(receipt_path, receipt)
    return receipt


if __name__ == "__main__":
    if os.geteuid() != 0:
        raise SystemExit("Install baseline finalization requires root")
    print(json.dumps(finalize(), sort_keys=True))
