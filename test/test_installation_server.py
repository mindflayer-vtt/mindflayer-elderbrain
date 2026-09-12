import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "appliance/lib"))
from installation_server import InstallationServer


class InstallationServerTests(unittest.TestCase):
    def test_private_input_uses_stdin_and_only_fixed_container_command(self):
        server = InstallationServer("/opt/mindflayer-elderbrain", 123)
        secret = "11" * 32
        def start(command, **kwargs):
            self.assertEqual(command[-5:], ["exec", "-T", "mindflayer-server", "node", "scripts/register-installation.js"])
            self.assertNotIn(secret, " ".join(command))
            self.assertEqual(kwargs["pass_fds"], (123,))
            def communicate(data, timeout):
                self.assertEqual(json.loads(data), {"id": "keypad", "secret": secret})
                self.assertEqual(timeout, 20)
                os.write(kwargs["stdout"].fileno(), b'{"id":"keypad","state":"registered"}')
            return Mock(returncode=0, communicate=communicate)
        with patch("installation_server.subprocess.Popen", side_effect=start):
            server.register({"id": "keypad", "secret": secret})

    def test_failure_does_not_expose_private_stderr(self):
        server = InstallationServer("/runtime", 123)
        def start(command, **kwargs):
            os.write(kwargs["stderr"].fileno(), b"secret-bearing-error")
            return Mock(returncode=1)
        with patch("installation_server.subprocess.Popen", side_effect=start):
            with self.assertRaises(RuntimeError) as raised:
                server.register({"id": "keypad", "secret": "11" * 32})
            self.assertNotIn("secret-bearing-error", str(raised.exception))

    def test_unsupported_operations_and_invalid_backups_never_start_process(self):
        server = InstallationServer("/runtime", 123)
        with patch("installation_server.subprocess.Popen") as process:
            with self.assertRaises(ValueError):
                server._call("arbitrary-script", {})
            with self.assertRaises(ValueError):
                server.prepare(b"short", b"short", {}, False)
            process.assert_not_called()

    def test_timeout_terminates_and_reaps_client(self):
        server = InstallationServer("/runtime", 123)
        process = Mock(pid=234, communicate=Mock(side_effect=subprocess.TimeoutExpired("docker", 20)))
        with patch("installation_server.subprocess.Popen", return_value=process), patch("installation_server.os.killpg") as kill:
            with self.assertRaises(RuntimeError):
                server.register({"id": "keypad", "secret": "11" * 32})
            kill.assert_called_once()
            process.wait.assert_called_once()


if __name__ == "__main__":
    unittest.main()
