"""Restore orchestration shared by manual and remote backup entry points."""
import time
import uuid
from pathlib import Path
from contextlib import nullcontext

from backup_service import save_record
from restore_transaction import RestoreTransaction


class RestoreCoordinator:
    """Service adapter implements snapshot, stop, validate, and resume_restored.

    Inputs must come from validated private staging and a fixed host target map.
    make_rollback must create and validate a complete archive while writers are
    stopped. No live target is replaced before that callback succeeds.
    """
    def __init__(self, maintenance, targets, make_rollback, *, refresh_targets=None,
                 before_restore=None, release_checkpoint=None, exclusive=nullcontext):
        self.maintenance = maintenance
        self.targets = targets
        self.services = maintenance.services
        self.make_rollback = make_rollback
        self.before_restore = before_restore or (lambda record: None)
        self.release_checkpoint = release_checkpoint or (lambda record: None)
        self.exclusive = exclusive
        # Persistent-directory aliases must point at the newly installed trees
        # before configuration validation or any writer restarts. Recovery must
        # repeat this even after a crash between rename and mount refresh.
        self.refresh_targets = refresh_targets or (lambda: None)

    def transaction(self, record):
        identity = record["id"]
        if len(identity) != 32 or any(c not in "0123456789abcdef" for c in identity):
            raise ValueError("Invalid maintenance transaction identity")
        return RestoreTransaction(self.maintenance.directory / ("restore-" + identity + ".json"), self.targets)

    def write(self, record, state):
        record["state"] = state
        save_record(self.maintenance.journal, record)

    def restore(self, staged_sources):
        with self.maintenance.locked():
            previous = self.maintenance.previous()
            if previous.get("state") not in (None, "completed", "failed", "recovered", "rolled-back"):
                raise RuntimeError("Interrupted maintenance requires recovery first")
            record = {"operation": "restore", "id": uuid.uuid4().hex,
                      "startedAt": time.time(), "services": self.services.snapshot(),
                      "targetKeys": sorted(self.targets)}
            transaction = self.transaction(record)
            self.write(record, "stopping")
            try:
                with self.exclusive():
                    self.services.stop(record["services"])
                    self.write(record, "creating-rollback")
                    self.before_restore(record)
                    self.write(record, "creating-rollback")
                    record["rollbackArchive"] = str(self.make_rollback(record))
                    self.write(record, "preparing-restore")
                    transaction.prepare(staged_sources)
                    self.write(record, "installing-restore")
                    transaction.apply()
                self.write(record, "verifying-restore")
                self.refresh_targets()
                self.services.validate()
                self.services.resume_restored(record["services"])
                transaction.commit()
                self.write(record, "completed")
                self.release_checkpoint(record)
                return record
            except Exception:
                # A failed start may have brought up some writers. Stop again
                # before rollback. If that fails, do not mutate files beneath them.
                self.write(record, "recovery-required")
                self.recover_locked(record)
                raise

    def recover(self):
        with self.maintenance.locked():
            return self.recover_locked(self.maintenance.previous())

    def recover_locked(self, record):
        if record.get("operation") != "restore":
            raise ValueError("This is not an interrupted restore")
        if record.get("state") in ("completed", "rolled-back"):
            self.release_checkpoint(record)
            return record
        transaction = self.transaction(record)
        self.write(record, "recovery-required")
        committed = False
        with self.exclusive():
            self.services.stop(record["services"])
            if transaction.journal.exists():
                committed = transaction.read()["state"] == "committed"
                if not committed:
                    transaction.rollback()
        self.refresh_targets()
        self.services.validate()
        self.services.resume_restored(record["services"])
        self.write(record, "completed" if committed else "rolled-back")
        self.release_checkpoint(record)
        return record


DATA_ROOTS = ("foundry", "elderbrain", "mindflayer", "firmware", "traefik", "browser")
RUNTIME_FILES = ("appliance.env", "compose.yaml", "VERSION", "sway.conf")
UNIT_FILES = ("elderbrain-stack.service", "elderbrain-management.service", "elderbrain-graphics.service", "elderbrain-backup.service")


def host_targets(state, runtime, host_root, *, persistent=False):
    targets = {name: state / name for name in DATA_ROOTS}
    targets["keypad-installations"] = state / "keypad-installations"
    targets['checkpoint-retention'] = state / 'snapshots/.retention'
    targets.update({"ssh-server": host_root / "etc/ssh", "ssh-root": host_root / "root/.ssh",
                    "ssh-admin": host_root / "home/elderbrain-installer/.ssh"})
    if persistent:
        # Replace canonical directories, never their mounted OS aliases.
        targets.update({name: state / 'host' / name
                        for name in ('ssh-server', 'ssh-root', 'ssh-admin')})
    targets.update({"runtime/" + name: runtime / name for name in RUNTIME_FILES})
    if persistent:
        targets.update({'runtime/' + name: state / 'host/runtime' / name
                        for name in ('appliance.env', 'sway.conf')})
    targets.update({"unit/" + name: host_root / "etc/systemd/system" / name for name in UNIT_FILES})
    return targets


def persistent_identity(state, host_root):
    marker = host_root / 'etc/elderbrain/storage.json'
    if not marker.exists() and not marker.is_symlink():
        return None
    from storage_guard import check, read_identity
    check(expected_path=marker, target=str(state))
    return read_identity(marker)


def alias_refresher(state, host_root, keys, identity):
    if identity is None:
        return None
    from host_bindings import refresh
    names = set(keys) & {'ssh-server', 'ssh-root', 'ssh-admin'}
    def refresh_verified():
        # Recheck the actual volume on every activation and rollback, not just
        # when the request started. A replaced/missing disk must stop recovery.
        if persistent_identity(state, host_root) != identity:
            raise ValueError('Persistent storage identity changed during restore')
        refresh(state, identity['data_uuid'], names, host_root=host_root)
    return refresh_verified


def checkpoint_hooks(state, runtime, host_root, identity):
    if identity is None:
        return {}
    from local_snapshots import Snapshots
    from checkpoint_compatibility import capture
    from snapshot_service import stable_settings
    def guard():
        if persistent_identity(state, host_root) != identity:
            raise ValueError('Persistent storage changed during restore checkpoint')
    snapshots = Snapshots(state, quiesce=nullcontext, guard=guard,
                          compatibility=lambda: capture(runtime))
    def before(record):
        record['rollbackCheckpoint'] = snapshots.create('before-restore', owner=record['id'], purpose='restore')['id']
    def release(record):
        if record.get('rollbackCheckpoint'):
            snapshots.unpin(record['rollbackCheckpoint'], record['id'], 'restore')
    return {'before_restore': before, 'release_checkpoint': release,
            'exclusive': lambda: stable_settings(state)}


def restore_host(archive, state, runtime, maintenance, *, host_root=Path("/")):
    import backup_archive
    from backup_service import create_backup
    identity = persistent_identity(state, host_root)
    with backup_archive.stage(archive, parent=maintenance.directory) as (contents, manifest):
        if manifest["applianceVersion"] != (runtime / "VERSION").read_text().strip():
            raise ValueError("Install the backup's appliance version before restoring it")
        required = set(DATA_ROOTS) | {"service-config", "ssh-server"}
        if not required <= set(manifest["roots"]):
            raise ValueError("Archive is missing required appliance configuration roots")
        if (contents / "service-config/VERSION").read_text().strip() != manifest["applianceVersion"]:
            raise ValueError("Archived service version disagrees with its manifest")
        sources = {name: contents / name for name in manifest["roots"] if name != "service-config"}
        # Older backups predate installation journals. Restore that empty state
        # rather than retain journals referring to credentials from the future.
        if "keypad-installations" not in sources:
            empty = contents / "keypad-installations"
            empty.mkdir(mode=0o700)
            sources["keypad-installations"] = empty
        sources.update({"runtime/" + name: contents / "service-config" / name for name in RUNTIME_FILES})
        sources.update({"unit/" + name: contents / "service-config/systemd" / name for name in UNIT_FILES})
        policy = contents / 'service-config/checkpoint-retention.json'
        if policy.exists() or policy.is_symlink():
            import json
            from local_snapshots import validate_retention
            if policy.is_symlink() or not policy.is_file() or policy.stat().st_size > 4096:
                raise ValueError('Invalid archived checkpoint retention settings')
            validate_retention(json.loads(policy.read_text()))
            # Normalize ownership of this root-managed setting independently of
            # archive metadata. Old archives leave the current policy untouched.
            import os
            policy.chmod(0o600)
            if os.geteuid() == 0:
                os.chown(policy, 0, 0)
            directory = state / 'snapshots'
            if directory.is_symlink():
                raise ValueError('Unsafe checkpoint storage')
            directory.mkdir(mode=0o700, exist_ok=True)
            sources['checkpoint-retention'] = policy
        known = host_targets(state, runtime, host_root, persistent=identity is not None)
        targets = {key: known[key] for key in sources}

        def rollback(record):
            return create_backup(state / "backups", state, runtime, maintenance,
                                 host_root=host_root, operation=record)["archive"]

        return RestoreCoordinator(maintenance, targets, rollback,
                                  refresh_targets=alias_refresher(state, host_root, targets, identity),
                                  **checkpoint_hooks(state, runtime, host_root, identity)).restore(sources)


def recover_host(state, runtime, maintenance, *, host_root=Path("/")):
    record = maintenance.previous()
    if record.get("operation") != "restore":
        raise ValueError("No restore recovery is recorded")
    identity = persistent_identity(state, host_root)
    known = host_targets(state, runtime, host_root, persistent=identity is not None)
    keys = record.get("targetKeys", [])
    if not keys or not set(keys) <= set(known):
        raise ValueError("Invalid restore target list")
    return RestoreCoordinator(maintenance, {key: known[key] for key in keys}, None,
                              refresh_targets=alias_refresher(state, host_root, keys, identity),
                              **checkpoint_hooks(state, runtime, host_root, identity)).recover()
