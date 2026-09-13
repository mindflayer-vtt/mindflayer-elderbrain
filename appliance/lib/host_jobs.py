"""Persistent, allowlisted host jobs. Live state is proven by a worker-held lock."""
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import threading
import uuid
import stat

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backup_service import save_record
from backup_uploads import UploadStore

COMMANDS = {"backup": ["backup"], "backup-recover": ["backup-recover"],
            "restore-recover": ["restore-recover"], "restore-preview": ["backup-preview"], "restore": ["restore"]}
ACTIVE = {"queued", "running"}
PRE_ACTIVATION = {None, 'verifying-release', 'downloading-host', 'downloading-dependencies',
                  'preparing-runtime', 'preparing-recovery', 'activating'}
COMMANDS.update({kind: [kind] for kind in ("borg-init", "borg-test", "borg-list", "borg-backup", "borg-fetch", "borg-recovery-kit")})
COMMANDS["backup-encrypted"] = ["backup-encrypted"]
COMMANDS["restore-preview-encrypted"] = []
COMMANDS["keypad-install"] = []
COMMANDS["snapshot-create"] = ["snapshot-create"]
COMMANDS["snapshot-recover"] = ["snapshot-recover"]
COMMANDS["snapshot-restore"] = ["snapshot-restore"]
COMMANDS['network-snapshot-restore'] = []
COMMANDS['update'] = []
COMMANDS['power'] = []


def _boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def _completed_power(record, power):
    """Return the public result when an accepted power request crossed a boot."""
    selected = record.get('request')
    backup = power.get('backup') if isinstance(power, dict) else None
    if (record.get('kind') != 'power' or not isinstance(selected, dict) or not isinstance(power, dict)
            or set(selected) != {'action', 'confirmPower'} or selected.get('confirmPower') is not True
            or selected.get('action') not in ('reboot', 'shutdown')
            or set(power) != {'state', 'action', 'bootId', 'backup', 'jobId'}
            or power.get('state') != 'requested' or power.get('jobId') != record.get('id')
            or power.get('action') != selected['action']
            or not isinstance(power.get('bootId'), str)
            or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', power['bootId'])
            or power['bootId'] == _boot_id()
            or not isinstance(backup, dict) or not set(backup) <= {'state', 'checkpoint'}
            or not isinstance(backup.get('state'), str)
            or any(not isinstance(value, str) for value in backup.values())):
        return None
    return {'state': 'requested', 'action': power['action'], 'backup': dict(backup)}


def _has_update_maintenance(record, maintenance):
    """Prove this update reached the recovery-owned transaction journal."""
    selected = record.get('request')
    return (isinstance(maintenance, dict) and isinstance(selected, dict)
            and maintenance.get('operation') == 'update'
            and maintenance.get('jobId') == record.get('id')
            and maintenance.get('version') == selected.get('version')
            and maintenance.get('manifestSha256') == selected.get('manifestSha256'))


class JobStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)

    def path(self, identity):
        if not re.fullmatch(r"[0-9a-f]{32}", identity):
            raise ValueError("Invalid job identity")
        return self.directory / (identity + ".json")

    def read(self, identity):
        path = self.path(identity)
        record = json.loads(path.read_text())
        if record["state"] in ACTIVE:
            fd = os.open(path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return record
                # Re-read under the lock: the worker may just have finished.
                record = json.loads(path.read_text())
                if record["state"] in ACTIVE:
                    result = None
                    if record.get('kind') == 'power':
                        power_path = self.directory.parent / 'power.json'
                        try:
                            result = _completed_power(record, json.loads(power_path.read_text()))
                        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
                            pass
                    if result is not None:
                        record.update(state='completed', stage='power-requested', finishedAt=time.time(), result=result)
                    elif record.get('kind') == 'update' and record.get('stage') in PRE_ACTIVATION:
                        maintenance_path = self.directory.parent / 'maintenance/maintenance.json'
                        try:
                            maintenance = json.loads(maintenance_path.read_text())
                        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
                            maintenance = None
                        if not _has_update_maintenance(record, maintenance):
                            record.update(state='failed', stage='failed-before-activation', finishedAt=time.time(),
                                          error='Update worker stopped before activation. The installed release was not changed; check the source and retry explicitly.')
                            save_record(path, record)
                            return record
                        record.update(state='interrupted', finishedAt=time.time(),
                                      error='Worker stopped during activation. Boot recovery must resolve the matching maintenance transaction.')
                    else:
                        record.update(state="interrupted", finishedAt=time.time(),
                                      error="Worker stopped before completion. Inspect maintenance state and run the matching recovery operation.")
                        if record.get("kind") == "keypad-install":
                            record["error"] = "Installation worker stopped. Retain this job's provisioning backups and private recovery journal; inspect the keypad before retrying."
                    save_record(path, record)
            finally:
                os.close(fd)
        return record

    def list(self):
        return sorted((self.read(path.stem) for path in self.directory.glob("*.json")
                       if re.fullmatch(r"[0-9a-f]{32}", path.stem)),
                      key=lambda record: record["createdAt"], reverse=True)

    def reconcile_update(self, outcome):
        """Called with maintenance locked after final recovery, never early boot.

        An unlocked worker descriptor plus exact job/version/digest correlation
        is required. Do not overwrite a live worker or infer success from a PID.
        """
        if outcome.get('operation') != 'update' or outcome.get('state') not in ('completed', 'rolled-back'):
            return False
        identity = outcome.get('jobId')
        if not isinstance(identity, str) or not re.fullmatch('[a-f0-9]{32}', identity):
            return False
        if not isinstance(outcome.get('id'), str) or not re.fullmatch('[a-f0-9]{32}', outcome['id']):
            return False
        path = self.path(identity)
        if not path.exists():
            return False
        descriptor = os.open(path.with_suffix('.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            record = json.loads(path.read_text())
            selected = record.get('request', {})
            if (record.get('id') != identity or record.get('kind') != 'update'
                    or record.get('state') not in ('queued', 'running', 'interrupted', 'failed')
                    or not isinstance(selected, dict)
                    or selected.get('version') != outcome.get('version')
                    or not isinstance(outcome.get('manifestSha256'), str)
                    or not re.fullmatch('[a-f0-9]{64}', outcome['manifestSha256'])
                    or selected.get('manifestSha256') != outcome['manifestSha256']):
                return False
            record.update(state=outcome['state'], stage='recovery-finished', finishedAt=time.time(),
                          result={key: outcome[key] for key in ('id', 'state', 'version')})
            record.pop('error', None)
            save_record(path, record)
            return True
        finally:
            os.close(descriptor)

    def open_backup(self, identity, *, recovery=False):
        record = self.read(identity)
        allowed = ("borg-recovery-kit",) if recovery else ("backup", "backup-encrypted")
        if record.get("kind") not in allowed or record.get("state") != "completed":
            raise ValueError("Backup is not ready for download")
        archive = Path(record["result"]["archive"])
        directory = self.directory.parent / ("recovery-kits" if recovery else "backups")
        pattern = r"elderbrain-[0-9a-f]{32}\.json" if recovery else r"elderbrain-[0-9a-f]{32}\.tar\.zst"
        if record.get("kind") == "backup-encrypted":
            pattern += r"\.gpg"
        if (archive.parent != directory or not re.fullmatch(pattern, archive.name)
                or directory.resolve() != directory):
            raise ValueError("Invalid backup artifact location")
        fd = os.open(archive, os.O_RDONLY | os.O_NOFOLLOW)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            os.close(fd)
            raise ValueError("Backup artifact is not a regular file")
        return os.fdopen(fd, "rb"), info.st_size

    def submit(self, kind, source=None, *, passphrase=None):
        if kind not in COMMANDS:
            raise ValueError("Unsupported job kind")
        details = {}
        installation_settings = None
        if kind in ("backup-encrypted", "restore-preview-encrypted"):
            from backup_crypto import validate_passphrase
            validate_passphrase(passphrase)
        elif passphrase is not None:
            raise ValueError("Unexpected passphrase")
        if kind == 'power':
            from power_service import request
            details['request'] = request(source)
        elif kind == 'update':
            from update_request import request
            details['request'] = request(source)
        elif kind == "keypad-install":
            from installation_job import admission
            request, installation_settings = admission(source, self.directory.parent)
            details = {"request": request, "revision": installation_settings["revision"]}
        elif kind == 'snapshot-restore':
            from checkpoint_restore import request
            details['request'] = request(source)
        elif kind == 'network-snapshot-restore':
            from network_checkpoint_restore import request
            details['request'] = request(source)
        elif kind in ("restore-preview", "restore-preview-encrypted"):
            UploadStore(self.directory.parent / "uploads").path(source)
            details["uploadId"] = source
        elif kind == "restore":
            preview = self.read(source)
            if preview.get("kind") not in ("restore-preview", "restore-preview-encrypted", "borg-fetch") or preview.get("state") != "completed":
                raise ValueError("Restore requires a completed preview")
            details = {"uploadId": preview["uploadId"], "sha256": preview["result"]["sha256"], "previewJob": source}
        elif kind == "borg-fetch":
            if not isinstance(source, str) or not re.fullmatch(r"elderbrain-[A-Za-z0-9_.:+-]{1,200}", source):
                raise ValueError("Invalid Borg archive name")
            details["archiveName"] = source
        elif source is not None:
            raise ValueError("Unexpected job input")
        gate = os.open(self.directory / "admission.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(gate, fcntl.LOCK_EX)
            from power_service import pending
            if pending(self.directory.parent):
                raise RuntimeError('A power operation is pending')
            if any(record["state"] in ACTIVE for record in self.list()):
                raise RuntimeError("Another host job is running")
            identity = uuid.uuid4().hex
            path = self.path(identity)
            fd = os.open(path.with_suffix(".lock"), os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            secret_fd = None
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                record = {"id": identity, "kind": kind, "state": "queued", "createdAt": time.time(), **details}
                if installation_settings is not None:
                    save_record(path.with_suffix(".settings"), installation_settings)
                save_record(path, record)
                try:
                    inherited = (fd,)
                    if passphrase is not None:
                        secret_fd = os.memfd_create("elderbrain-job-secret", os.MFD_CLOEXEC)
                        os.write(secret_fd, (passphrase + "\n").encode())
                        os.lseek(secret_fd, 0, os.SEEK_SET)
                        inherited += (secret_fd,)
                    # Inherited lock bridges admission to worker startup, avoiding
                    # any interval in which a queued job is misread as interrupted.
                    # A new session alone stays in management.service's cgroup.
                    # A separate scope preserves inherited lock/secret FDs while
                    # surviving a bridge restart. No credentials enter unit
                    # properties, argv, the journal, or temporary disk files.
                    worker_command = [sys.executable, str(Path(__file__).resolve()),
                        'worker', str(self.directory), identity, str(fd), str(secret_fd if secret_fd is not None else -1)]
                    if kind == 'update':
                        worker_command = ['/usr/bin/python3', '-I', '-B', '/usr/libexec/elderbrain-recovery.py',
                                          'job', identity, str(fd)]
                    process = subprocess.Popen(['systemd-run', '--scope', '--quiet', '--collect',
                                                '--unit=elderbrain-job-' + identity,
                                                '--expand-environment=no', '--',
                                                *worker_command],
                                               pass_fds=inherited, stdin=subprocess.DEVNULL,
                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                               start_new_session=True)
                    # Worker owns completion; PID alone is never evidence of liveness.
                    threading.Thread(target=process.wait, daemon=True).start()
                except Exception:
                    record.update(state="failed", finishedAt=time.time(), error="Unable to start host worker")
                    save_record(path, record)
                    raise
                return record
            finally:
                if secret_fd is not None:
                    os.close(secret_fd)
                os.close(fd)
        finally:
            os.close(gate)


def worker(directory, identity, lock_fd, *, executable="/usr/local/sbin/elderbrain", secret_fd=None):
    store = JobStore(directory)
    path = store.path(identity)
    record = json.loads(path.read_text())
    if record.get("kind") not in COMMANDS or record.get("state") != "queued":
        raise ValueError("Invalid queued job")
    record.update(state="running", startedAt=time.time())
    save_record(path, record)
    try:
        if record['kind'] == 'power':
            from power_service import run_job
            record['stage'] = 'requesting-power'
            save_record(path, record)
            result = run_job(store.directory.parent, identity, record['request'])
            record['result'] = {key: result[key] for key in ('state', 'action', 'backup') if key in result}
            record['state'] = 'completed'  # Request accepted, not proof of physical shutdown.
            return
        if record['kind'] == 'update':
            from update_job import run_update
            def progress(stage):
                record['stage'] = stage
                save_record(path, record)
            result = run_update(store.directory.parent, identity, record['request'], progress=progress)
            record['result'] = {key: result[key] for key in ('id', 'state', 'version', 'remoteBackup') if key in result}
            record['state'] = 'completed'
            return
        if record['kind'] == 'network-snapshot-restore':
            from network_checkpoint_restore import request, coordinator
            selected = request(record['request'])
            runtime = Path(os.environ.get('ELDERBRAIN_COMPOSE_DIR', '/opt/mindflayer-elderbrain'))
            result = coordinator(store.directory.parent, runtime).start(
                selected['checkpoint'], selected['interface'], confirmation_digest=selected['confirmationDigest'], transaction_id=identity)
            record['result'] = {key: result[key] for key in ('id', 'phase', 'deadline', 'interface')}
            record['state'] = 'completed'
            return
        if record["kind"] == "keypad-install":
            from installation_job import run_installation
            from installation_backend import InstallationBackend
            from backup_service import Maintenance, HostServices
            runtime = Path(os.environ.get("ELDERBRAIN_COMPOSE_DIR", "/opt/mindflayer-elderbrain"))
            state = store.directory.parent
            settings = json.loads(path.with_suffix(".settings").read_text())
            maintenance = Maintenance(state / "maintenance", HostServices(runtime))
            with maintenance.locked() as maintenance_fd:
                if maintenance.previous().get("state") not in (None, 'completed', 'failed', 'recovered', 'rolled-back'):
                    raise RuntimeError("Recover appliance maintenance before installation")
                backend = InstallationBackend(runtime, lock_fd, (maintenance_fd,))
                def progress(update):
                    record["stage"] = update["stage"]
                    save_record(path, record)
                result = run_installation(state / "keypad-installations" / identity,
                                          record["request"], settings, backend, progress)
                record["result"] = result
                record["state"] = "completed"
            return
        if record["kind"] == "restore-preview-encrypted":
            from backup_crypto import decrypted
            from backup_archive import validate, preview
            if secret_fd is None:
                raise ValueError("Decryption passphrase is unavailable; submit a new job")
            with os.fdopen(os.dup(secret_fd), "rb") as secret:
                passphrase = secret.read(8193).decode().removesuffix("\n")
            uploads = UploadStore(store.directory.parent / "uploads")
            archive, _ = uploads.verify(record["uploadId"])
            with decrypted(archive, passphrase, parent=uploads.directory) as plaintext:
                manifest = validate(plaintext)
                with plaintext.open("rb") as data:
                    uploaded = uploads.receive(data, plaintext.stat().st_size)
            # A successful preview references the verified plaintext, so confirmation
            # needs no persisted password and uses the normal checksum-checked restore.
            record["uploadId"] = uploaded["id"]
            record["result"] = {"preview": preview(manifest), "sha256": uploaded["sha256"]}
            record["state"] = "completed"
            return
        arguments = list(COMMANDS[record["kind"]])
        if record['kind'] == 'snapshot-restore':
            from checkpoint_restore import request
            selected = request(record['request'])
            arguments += ['--checkpoint', selected['checkpoint'], '--confirm-restore']
            for component in selected['components']:
                arguments += ['--component', component]
        checksum = None
        inherited = (lock_fd,)
        if record["kind"] == "backup-encrypted":
            if secret_fd is None:
                raise ValueError("Encryption passphrase is unavailable; submit a new job")
            arguments += ["--passphrase-fd", str(secret_fd)]
            inherited += (secret_fd,)
        if record["kind"] == "borg-fetch":
            arguments.append(record["archiveName"])
        if record["kind"] in ("restore-preview", "restore"):
            archive, checksum = UploadStore(store.directory.parent / "uploads").verify(record["uploadId"], record.get("sha256"))
            arguments.append(str(archive))
            if record["kind"] == "restore":
                arguments.append("--confirm-restore")
        # Raw stderr can contain credentials. It remains root-private and is never
        # returned by the jobs API. Only known successful JSON results are exposed.
        stdout_fd = os.open(path.with_suffix(".stdout"), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        stderr_fd = os.open(path.with_suffix(".stderr"), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(stdout_fd, "wb") as output, os.fdopen(stderr_fd, "wb") as errors:
            result = subprocess.run([executable, *arguments],
                                    stdin=subprocess.DEVNULL, stdout=output, stderr=errors,
                                    pass_fds=inherited, timeout=24 * 3600)
        if result.returncode:
            raise RuntimeError("Host operation failed")
        result_path = path.with_suffix(".stdout")
        if result_path.stat().st_size > 1024 * 1024:
            raise ValueError("Host result exceeds limit")
        result = json.loads(result_path.read_text())
        # Recovery journals include host paths and internal service state; omit them.
        if record["kind"] in ("backup", "backup-encrypted"):
            record["result"] = {"archive": result["archive"], "preview": result["preview"], "encrypted": record["kind"] == "backup-encrypted"}
        elif record["kind"] == "restore-preview":
            record["result"] = {"preview": result, "sha256": checksum}
        elif record["kind"] == "borg-fetch":
            UploadStore(store.directory.parent / "uploads").path(result["uploadId"])
            record["uploadId"] = result["uploadId"]
            record["result"] = {"preview": result["preview"], "sha256": result["sha256"]}
        elif record["kind"] == "snapshot-create":
            checkpoint = result['checkpoint']
            record['result'] = {'state': result['state'], 'checkpoint':
                {key: checkpoint[key] for key in ('version', 'id', 'createdAt', 'reason')}}
        elif record["kind"] in ("borg-list", "borg-test"):
            record["result"] = {"state": result["state"], "archives": result["archives"]}
        elif record["kind"] == "borg-recovery-kit":
            record["result"] = {"archive": result["archive"]}
        else:
            record["result"] = {"state": result["state"]}
        record["state"] = "completed"
    except Exception:
        if record['kind'] == 'update':
            import traceback
            diagnostic = os.open(path.with_suffix('.stderr'), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            with os.fdopen(diagnostic, 'w') as output:
                output.write(traceback.format_exc()[-65536:])
                output.flush()
                os.fsync(output.fileno())
        record.update(state="failed", error="Host operation failed. Inspect the root-private job diagnostics and maintenance state before retrying.")
        if record["kind"] == "keypad-install":
            record["error"] = "Installation stopped at " + record.get("stage", "preflight") + "; retain this job's keypad provisioning backups and private recovery journal before retrying."
    finally:
        if secret_fd is not None:
            os.close(secret_fd)
        record["finishedAt"] = time.time()
        save_record(path, record)
        os.close(lock_fd)


if __name__ == "__main__":
    if len(sys.argv) != 6 or sys.argv[1] != "worker":
        raise SystemExit("Internal job worker only")
    worker(sys.argv[2], sys.argv[3], int(sys.argv[4]), secret_fd=int(sys.argv[5]) if int(sys.argv[5]) >= 0 else None)
