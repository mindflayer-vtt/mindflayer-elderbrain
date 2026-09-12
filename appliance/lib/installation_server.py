"""Private container command bridge used by the host installation backend."""
import base64
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile

from installation_job import validate_plan


class InstallationServer:
    def __init__(self, runtime, lock_fd, extra_lock_fds=()):
        runtime = Path(runtime)
        self.compose = ["docker", "compose", "--env-file", str(runtime / "appliance.env"),
                        "-f", str(runtime / "compose.yaml")]
        self.lock_fd = lock_fd
        self.extra_lock_fds = tuple(extra_lock_fds)

    def _call(self, operation, payload):
        limits = {"prepare-installation": 20, "register-installation": 20, "verify-installation": 140, "installation-capabilities": 10}
        if operation not in limits:
            raise ValueError("Unsupported private installation command")
        data = json.dumps(payload).encode()
        if len(data) > 16384:
            raise ValueError("Installation input exceeds limit")
        command = self.compose + ["exec", "-T", "mindflayer-server", "node", "scripts/" + operation + ".js"]
        # Anonymous mode-0600 files avoid buffering child output in memory or
        # accidentally publishing credentials as part of host job diagnostics.
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=output, stderr=errors,
                                       start_new_session=True, pass_fds=(self.lock_fd, *self.extra_lock_fds))
            try:
                process.communicate(data, timeout=limits[operation])
            except BaseException:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                raise RuntimeError("Private installation command stopped; inspect the saved plan before retrying") from None
            if process.returncode:
                raise RuntimeError("Private installation command failed; check server compatibility and saved installation state")
            if output.tell() > 16384:
                raise ValueError("Private installation result exceeds limit")
            output.seek(0)
            try:
                result = json.load(output)
            except (ValueError, UnicodeError):
                raise ValueError("Invalid private installation response") from None
        if not isinstance(result, dict):
            raise ValueError("Invalid private installation response")
        return result

    def prepare(self, sector_a, sector_b, settings, adopt):
        if not all(isinstance(sector, bytes) and len(sector) == 4096 for sector in (sector_a, sector_b)):
            raise ValueError("Invalid provisioning sector backups")
        if type(adopt) is not bool:
            raise ValueError("Explicit adoption must be boolean")
        result = self._call("prepare-installation", {"sectorA": base64.b64encode(sector_a).decode(),
                            "sectorB": base64.b64encode(sector_b).decode(), "settings": settings, "adopt": adopt})
        validate_plan(result)
        return result

    def register(self, credential):
        result = self._call("register-installation", credential)
        if result != {"id": credential["id"], "state": "registered"}:
            raise ValueError("Installation credential was not registered")

    def verify_online(self, identity, firmware, digest, not_before):
        return self._call("verify-installation", {"id": identity, "firmware": firmware, "digest": digest, "notBefore": not_before})
