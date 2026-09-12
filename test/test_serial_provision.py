from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "appliance/lib"))
from serial_provision import send, acknowledge, provision


class SerialProvisionTests(unittest.TestCase):
    def test_partial_and_temporarily_blocked_writes_complete(self):
        with patch("serial_provision.os.write", side_effect=[BlockingIOError(), 2, 2]) as write, patch("serial_provision.select.select"):
            send(123, b"data")
            self.assertEqual(write.call_count, 3)
            self.assertEqual(bytes(write.call_args.args[1]), b"ta")

    def test_write_timeout_and_zero_write_stop(self):
        with patch("serial_provision.time.monotonic", side_effect=[0, 6]), patch("serial_provision.os.write") as write:
            with self.assertRaises(TimeoutError):
                send(123, b"data")
            write.assert_not_called()
        with patch("serial_provision.os.write", return_value=0):
            with self.assertRaises(RuntimeError):
                send(123, b"data")

    def test_split_ack_is_detected_without_echoing_serial_data(self):
        with patch("serial_provision.select.select", return_value=([123], [], [])), patch("serial_provision.os.read", side_effect=[b"private-data\nPROVISION", b"ING OK\n"]):
            self.assertIsNone(acknowledge(123))

    def test_error_disconnect_and_missing_ack_fail(self):
        for data in [b"PROVISIONING ERROR\nPROVISIONING OK", b""]:
            with patch("serial_provision.select.select", return_value=([123], [], [])), patch("serial_provision.os.read", return_value=data):
                with self.assertRaises(RuntimeError):
                    acknowledge(123)
        with patch("serial_provision.time.monotonic", side_effect=[0, 21]):
            with self.assertRaises(TimeoutError):
                acknowledge(123)

    def test_invalid_envelope_never_opens_serial_port(self):
        with patch("serial_provision.os.open") as opened:
            with self.assertRaises(ValueError):
                provision("/dev/ttyUSB0", b"invalid")
            opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
