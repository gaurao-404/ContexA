#!/usr/bin/env python3
"""Perform a private S3-compatible write/read/delete check using ContexA settings."""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import S3_BUCKET, S3_REGION, S3_ENDPOINT_URL  # noqa: E402
from app.object_storage import store_bytes, read_bytes, delete_object  # noqa: E402


def main() -> int:
    if not S3_BUCKET:
        raise SystemExit("S3_BUCKET is not configured; private object storage is not ready.")
    payload = f"ContexA storage health check {uuid.uuid4()}".encode()
    key = f"healthchecks/{uuid.uuid4()}.txt"
    stored = None
    try:
        stored = store_bytes(payload, key, "text/plain")
        if read_bytes(stored) != payload:
            raise RuntimeError("Object read-back did not match the uploaded bytes.")
        print(f"Private object storage write/read passed (bucket={S3_BUCKET}, region={S3_REGION}, endpoint={'custom' if S3_ENDPOINT_URL else 'AWS'}).")
    finally:
        if stored:
            delete_object(stored)
    print("Temporary health-check object deleted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
