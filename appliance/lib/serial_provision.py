"""Bounded host adaptation of mindflayer-server's serial-provision-transport.py.

Uses its RTS double-reset sequence and 115200-baud envelope delivery. A serial
ACK is only transport success; the installation coordinator verifies online state.
"""
import fcntl
import os
import select
import stat
import sys
import termios
import time
import zlib


def send(fd, envelope):
    deadline = time.monotonic() + 5
    view = memoryview(envelope)
    while view:
        if time.monotonic() >= deadline:
            raise TimeoutError("Serial provisioning write timed out")
        try:
            written = os.write(fd, view)
            if written == 0:
                raise RuntimeError("Serial device stopped accepting data")
            view = view[written:]
        except BlockingIOError:
            select.select([], [fd], [], 0.1)


def acknowledge(fd):
    deadline = time.monotonic() + 20
    received = b""
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.25)
        if not ready:
            continue
        try:
            data = os.read(fd, 4096)
        except BlockingIOError:
            continue
        if not data:
            raise RuntimeError("Serial device disconnected during provisioning")
        received = (received + data)[-8192:]
        if b"PROVISIONING ERROR" in received:
            raise RuntimeError("Device rejected provisioning envelope")
        if b"PROVISIONING OK" in received:
            return
    raise TimeoutError("Serial provisioning acknowledgement timed out")


def provision(port, envelope):
    if (not isinstance(envelope, bytes) or not 12 <= len(envelope) <= 1035 or envelope[:5] != b"MFP1\x01" or
            int.from_bytes(envelope[5:7], "big") != len(envelope) - 11 or
            int.from_bytes(envelope[-4:], "big") != zlib.crc32(envelope[:-4])):
        raise ValueError("Invalid provisioning envelope")
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        if not stat.S_ISCHR(os.fstat(fd).st_mode):
            raise ValueError("Serial target is not a character device")
        fcntl.ioctl(fd, termios.TIOCEXCL)
        attributes = termios.tcgetattr(fd)
        attributes[:4] = [0, 0, termios.CS8 | termios.CLOCAL | termios.CREAD, 0]
        attributes[4:6] = [termios.B115200, termios.B115200]
        termios.tcsetattr(fd, termios.TCSANOW, attributes)
        termios.tcflush(fd, termios.TCIFLUSH)
        fcntl.ioctl(fd, termios.TIOCMBIC, int(termios.TIOCM_DTR).to_bytes(4, sys.byteorder))
        rts = int(termios.TIOCM_RTS).to_bytes(4, sys.byteorder)
        for pause_after in (0.5, 1.2):
            fcntl.ioctl(fd, termios.TIOCMBIS, rts)
            time.sleep(0.1)
            fcntl.ioctl(fd, termios.TIOCMBIC, rts)
            time.sleep(pause_after)
        send(fd, envelope)
        acknowledge(fd)
    finally:
        os.close(fd)
