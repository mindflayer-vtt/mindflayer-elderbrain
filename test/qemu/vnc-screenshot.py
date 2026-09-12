#!/usr/bin/env python3
"""Capture one raw framebuffer from a no-password local QEMU VNC server."""
import socket, struct, sys, time

host, port, output = "127.0.0.1", 5900, sys.argv[1]
def exact(sock, size):
    data = b""
    while len(data) < size: data += sock.recv(size - len(data))
    return data

with socket.create_connection((host, port), 5) as sock:
    version = exact(sock, 12); sock.sendall(version)
    count = exact(sock, 1)[0]; kinds = exact(sock, count)
    if 1 not in kinds: raise RuntimeError("VNC server does not offer no-auth mode")
    sock.sendall(b"\x01"); result = struct.unpack(">I", exact(sock, 4))[0]
    if result: raise RuntimeError("VNC authentication failed")
    sock.sendall(b"\x01")
    width, height = struct.unpack(">HH", exact(sock, 4)); pixel = exact(sock, 16)
    name_size = struct.unpack(">I", exact(sock, 4))[0]; exact(sock, name_size)
    if len(sys.argv) > 2:
        for key in [0xff0d, *map(ord, sys.argv[2]), 0xff0d]:
            sock.sendall(struct.pack(">BBHI", 4, 1, 0, key) + struct.pack(">BBHI", 4, 0, 0, key))
            time.sleep(0.015)
        time.sleep(1)
    bpp, depth, big, true, rmax, gmax, bmax, rshift, gshift, bshift = struct.unpack(">BBBBHHHBBBxxx", pixel)
    if not true or bpp not in (16, 32): raise RuntimeError("unsupported VNC pixel format")
    sock.sendall(struct.pack(">BBHi", 2, 0, 1, 0))
    sock.sendall(struct.pack(">BBHHHH", 3, 0, 0, 0, width, height))
    while True:
        message = exact(sock, 1)[0]
        if message == 0: break
        if message == 2: continue
        if message == 3:
            size = struct.unpack(">I", exact(sock, 7)[3:])[0]; exact(sock, size); continue
        raise RuntimeError(f"unsupported VNC message {message}")
    rectangles = struct.unpack(">H", exact(sock, 3)[1:])[0]
    canvas = bytearray(width * height * 3); byte_width = bpp // 8
    for _ in range(rectangles):
        x, y, rw, rh, encoding = struct.unpack(">HHHHi", exact(sock, 12))
        if encoding != 0: raise RuntimeError(f"unexpected VNC encoding {encoding}")
        raw = exact(sock, rw * rh * byte_width)
        order = "big" if big else "little"
        for row in range(rh):
            for col in range(rw):
                at = (row * rw + col) * byte_width
                value = int.from_bytes(raw[at:at+byte_width], order)
                rgb = ((value >> rshift) & rmax) * 255 // rmax, ((value >> gshift) & gmax) * 255 // gmax, ((value >> bshift) & bmax) * 255 // bmax
                target = ((y + row) * width + x + col) * 3; canvas[target:target+3] = bytes(rgb)
with open(output, "wb") as image: image.write(f"P6\n{width} {height}\n255\n".encode() + canvas)
