"""Private host adapter for the installer from a verified release bundle.

No public API: callers must hold the installation/maintenance lock and retain
this directory for recovery. Provisioning and authenticated online verification
must follow successful flashing; this adapter does not claim job completion.
"""
import fcntl
import importlib.util
import os
import re
from pathlib import Path
import signal
import subprocess
from types import SimpleNamespace
import uuid

from backup_service import save_record
from serial_bundle import verify


class SerialInstaller:
    def __init__(self, archive, public_key, version, directory, *, python, esptool,
                 resolve_port, capabilities, lock_fd, extra_lock_fds=()):
        # Keep the authoritative job lock alive even if the worker is killed
        # while a flasher child is still accessing hardware.
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.lock_fd = lock_fd
        self.extra_lock_fds = tuple(extra_lock_fds)
        manifest, files = verify(archive, public_key, expected_version=version)
        if (not isinstance(capabilities, dict) or
                3 not in capabilities.get("deviceProtocolVersions", []) or
                capabilities.get("configurationProof") != "sha256-canonical-envelope-v2"):
            raise ValueError("Server upgrade required before installing protocol-v3 firmware")
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        for name, data in files.items():
            fd = os.open(self.directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
        self.resolve_port = resolve_port
        self.port = resolve_port()
        self.mac = None
        self.args = SimpleNamespace(python=str(python), esptool=str(esptool), port=self.port,
                                    rboot=self.directory / "rboot.bin", metadata_a=self.directory / "metadata-a.bin",
                                    metadata_b=self.directory / "metadata-b.bin", slot_a=self.directory / "application.bin")
        spec = importlib.util.spec_from_file_location("verified_installer_" + uuid.uuid4().hex, self.directory / "install-rboot.py")
        self.installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.installer)
        self.installer.run = self.run
        self.images = self.installer.preflight(self.args)
        self.before = None
        save_record(self.directory / "release.json", {"version": manifest["version"], "hardware": manifest["hardware"]})

    def run(self, python, esptool, port, *arguments, capture=False):
        if self.resolve_port() != self.port or port != self.port:
            raise RuntimeError("USB target changed; retain backups and reconnect the original keypad")
        # A timed-out flasher must not outlive its worker and continue writing.
        # Outputs remain private; no raw USB/tool diagnostics cross the bridge.
        with (self.directory / "serial.stdout").open("ab") as output, (self.directory / "serial.stderr").open("ab") as errors:
            os.chmod(output.name, 0o600)
            os.chmod(errors.name, 0o600)
            offset = output.tell()
            guard = ["--expected-mac", self.mac] if self.mac else []
            process = subprocess.Popen([python, esptool, *guard, "--chip", "esp8266", "--port", port, *map(str, arguments)],
                                       stdin=subprocess.DEVNULL, stdout=output, stderr=errors,
                                       start_new_session=True, pass_fds=(self.lock_fd, *self.extra_lock_fds))
            try:
                code = process.wait(timeout=180)
            except BaseException:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                raise
            if code:
                raise RuntimeError("Serial operation failed; retain backups and inspect private diagnostics")
        if not capture:
            return ""
        with (self.directory / "serial.stdout").open("rb") as output:
            output.seek(offset)
            data = output.read(65537)
        if len(data) > 65536:
            raise ValueError("Serial probe output exceeds limit")
        text = data.decode("utf8", errors="replace")
        if arguments and arguments[0] == "chip_id":
            matches = re.findall(r"^MAC:\s*([a-f0-9]{2}(?::[a-f0-9]{2}){5})\s*$", text, re.I | re.M)
            if len(matches) != 1 or (self.mac is not None and matches[0].lower() != self.mac):
                raise RuntimeError("Keypad MAC is missing or changed since inspection")
            self.mac = matches[0].lower()
            save_record(self.directory / "hardware.json", {"chip": "esp8266", "mac": self.mac})
        return text

    def backup(self):
        self.installer.assert_esp8266(self.args.python, self.args.esptool, self.port)
        self.installer.assert_flash_size(self.args.python, self.args.esptool, self.port)
        directory = self.directory / "original-provisioning"
        directory.mkdir(mode=0o700)
        before = {}
        for address, name in self.installer.PROVISIONING:
            before[address] = self.installer.backup_sector(self.args, address, directory / name)
        save_record(directory / "checksums.json", before)
        self.before = before
        return tuple((directory / name).read_bytes() for _, name in self.installer.PROVISIONING)

    def flash(self):
        if self.before is None:
            raise RuntimeError("Back up and inspect provisioning before flashing")
        original = self.installer.backup_sector

        def checked_backup(args, address, target):
            digest = original(args, address, target)
            if digest != self.before[address]:
                raise RuntimeError("Provisioning changed since inspection; stop and retain both backups")
            return digest

        self.installer.backup_sector = checked_backup
        try:
            self.installer.install(self.args, self.images, self.directory / "flash-backup")
        finally:
            self.installer.backup_sector = original
