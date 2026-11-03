#!/usr/bin/env python3
"""Ping the configured ClamAV daemon and optionally verify EICAR rejection."""
from __future__ import annotations

import os
import socket
import struct


def command(host: str, port: int, payload: bytes) -> bytes:
    with socket.create_connection((host, port), timeout=8) as sock:
        sock.settimeout(20)
        sock.sendall(payload)
        response = bytearray()
        while len(response) < 4096:
            part = sock.recv(1024)
            if not part:
                break
            response.extend(part)
            if b"\0" in part or b"\n" in part:
                break
    return bytes(response).strip(b"\0\r\n ")


def main() -> int:
    host = os.getenv("CLAMD_HOST", "127.0.0.1")
    port = int(os.getenv("CLAMD_PORT", "3310"))
    pong = command(host, port, b"zPING\0")
    if pong != b"PONG":
        raise RuntimeError(f"Unexpected ClamAV ping response: {pong!r}")
    print(f"ClamAV daemon ping passed: {host}:{port}")

    eicar = b'X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*'
    instream = b"zINSTREAM\0" + struct.pack("!I", len(eicar)) + eicar + struct.pack("!I", 0)
    result = command(host, port, instream)
    if b"Eicar-Test-Signature FOUND" not in result:
        raise RuntimeError(f"ClamAV did not identify the harmless EICAR test signature: {result!r}")
    print("ClamAV INSTREAM test passed: EICAR test signature was correctly detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
