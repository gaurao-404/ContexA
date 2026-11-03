from __future__ import annotations

import pytest
from fastapi import HTTPException

from app import upload_security


class FakeClamSocket:
    def __init__(self, response: bytes):
        self.response = response
        self.sent = bytearray()
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def sendall(self, payload: bytes):
        self.sent.extend(payload)

    def recv(self, _size: int) -> bytes:
        result, self.response = self.response, b""
        return result


def test_clamav_disabled_reports_not_configured(monkeypatch):
    monkeypatch.setattr(upload_security, "UPLOAD_SCAN_MODE", "disabled")
    assert upload_security.clamav_scan(b"safe") == {"status": "not_configured"}


def test_clamav_clean_result_is_reported(monkeypatch):
    fake = FakeClamSocket(b"stream: OK\0")
    monkeypatch.setattr(upload_security, "UPLOAD_SCAN_MODE", "clamd")
    monkeypatch.setattr(upload_security.socket, "create_connection", lambda *_a, **_k: fake)
    result = upload_security.clamav_scan(b"document-bytes")
    assert result == {"status": "clean"}
    assert b"zINSTREAM" in fake.sent
    assert fake.closed


def test_clamav_detected_payload_is_rejected(monkeypatch):
    fake = FakeClamSocket(b"stream: Eicar-Test-Signature FOUND\0")
    monkeypatch.setattr(upload_security, "UPLOAD_SCAN_MODE", "clamd")
    monkeypatch.setattr(upload_security.socket, "create_connection", lambda *_a, **_k: fake)
    with pytest.raises(HTTPException) as exc:
        upload_security.clamav_scan(b"malware")
    assert exc.value.status_code == 422


def test_clamav_unavailable_fails_closed(monkeypatch):
    monkeypatch.setattr(upload_security, "UPLOAD_SCAN_MODE", "clamd")
    def unavailable(*_a, **_k):
        raise OSError("connection refused")
    monkeypatch.setattr(upload_security.socket, "create_connection", unavailable)
    with pytest.raises(HTTPException) as exc:
        upload_security.clamav_scan(b"document")
    assert exc.value.status_code == 503
