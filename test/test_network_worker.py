import importlib.util
from pathlib import Path
import signal
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

LIB = Path(__file__).resolve().parents[1] / 'appliance/lib'
sys.path.insert(0, str(LIB))
spec = importlib.util.spec_from_file_location('network_worker', LIB / 'network_worker.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class NetworkWorkerTests(unittest.TestCase):
    def process(self, popen):
        process = MagicMock()
        process.pid = 4321
        popen.return_value.__enter__.return_value = process
        return process

    @patch.object(module.subprocess, 'Popen')
    def test_apply_is_bounded_and_does_not_log_backend_output(self, popen):
        process = self.process(popen)
        process.wait.return_value = 0
        module.run_netplan('apply')
        popen.assert_called_once_with(['netplan', 'apply'], stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True, umask=0o022)
        process.wait.assert_called_once_with(timeout=30)

    @patch.object(module.os, 'killpg')
    @patch.object(module.subprocess, 'Popen')
    def test_timeout_kills_and_reaps_the_process_group(self, popen, killpg):
        process = self.process(popen)
        process.wait.side_effect = [subprocess.TimeoutExpired('netplan', 30), -9]
        with self.assertRaisesRegex(RuntimeError, '^Network operation timed out$'):
            module.run_netplan('apply')
        killpg.assert_called_once_with(4321, signal.SIGKILL)
        self.assertEqual(process.wait.call_count, 2)

    @patch.object(module.subprocess, 'Popen')
    def test_failures_are_generic_and_operations_are_allowlisted(self, popen):
        process = self.process(popen)
        process.wait.return_value = 1
        with self.assertRaisesRegex(RuntimeError, '^Network operation failed$'):
            module.run_netplan('generate')
        popen.reset_mock()
        with self.assertRaises(ValueError):
            module.run_netplan('arbitrary-command')
        popen.assert_not_called()
