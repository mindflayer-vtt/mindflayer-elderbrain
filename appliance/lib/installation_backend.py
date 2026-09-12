"""Production backend for the host installation coordinator."""
from pathlib import Path

from installation_server import InstallationServer
from keypad_inventory import usb_serial_devices
from serial_install import SerialInstaller
from serial_provision import provision
from serial_release import download


class InstallationBackend(InstallationServer):
    def __init__(self, runtime, lock_fd, extra_lock_fds=()):
        super().__init__(runtime, lock_fd, extra_lock_fds)
        self.runtime = Path(runtime)

    def preflight(self, request, directory):
        python = self.runtime / "serial-venv/bin/python"
        esptool = self.runtime / "esptool-runner.py"
        if not python.is_file() or not esptool.is_file():
            raise RuntimeError("Serial installation tools are not installed")
        capabilities = self._call("installation-capabilities", {})
        if capabilities.get("configurationProof") != "sha256-canonical-envelope-v2" or 3 not in capabilities.get("deviceProtocolVersions", []):
            raise RuntimeError("Upgrade the server before installing protocol-v3 firmware")
        selected = [device for device in usb_serial_devices() if device["id"] == request["usbId"]]
        if len(selected) != 1:
            raise RuntimeError("Selected USB device is no longer present")
        expected = selected[0]

        def resolve_port():
            current = [device for device in usb_serial_devices() if device["id"] == expected["id"]]
            if len(current) != 1 or any(current[0][key] != expected[key] for key in ("port", "serial", "vendorId", "productId")):
                raise RuntimeError("Selected USB device changed; reconnect the original keypad")
            return current[0]["port"]

        archive = Path(directory) / "release.tar.gz"
        public_key = self.runtime / "firmware-signing-public.pem"
        download(request["version"], archive, public_key)
        return SerialInstaller(archive, public_key, request["version"], Path(directory) / "serial",
                               python=python, esptool=esptool, resolve_port=resolve_port,
                               capabilities=capabilities, lock_fd=self.lock_fd, extra_lock_fds=self.extra_lock_fds)

    def provision(self, serial, envelope):
        if serial.resolve_port() != serial.port:
            raise RuntimeError("USB device changed before provisioning")
        serial.installer.assert_esp8266(serial.args.python, serial.args.esptool, serial.port)
        provision(serial.port, envelope)
