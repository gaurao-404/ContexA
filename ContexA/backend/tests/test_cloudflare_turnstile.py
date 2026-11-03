from io import BytesIO

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import main


def request_with_headers(headers=None):
    return Request({
        "type": "http", "http_version": "1.1", "method": "POST",
        "scheme": "https", "path": "/api/auth/login", "raw_path": b"/api/auth/login",
        "query_string": b"", "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": ("203.0.113.10", 43120), "server": ("api.example.test", 443),
    })


def test_turnstile_is_optional_when_no_secret_is_configured(monkeypatch):
    monkeypatch.setattr(main, "TURNSTILE_SECRET_KEY", "")
    main._verify_turnstile(None, request_with_headers(), "auth")


def test_turnstile_rejects_missing_token_when_enabled(monkeypatch):
    monkeypatch.setattr(main, "TURNSTILE_SECRET_KEY", "test-secret")
    with pytest.raises(HTTPException) as error:
        main._verify_turnstile(None, request_with_headers(), "auth")
    assert error.value.status_code == 400
    assert "verification" in error.value.detail.lower()


def test_turnstile_posts_token_and_accepts_matching_hostname_and_action(monkeypatch):
    monkeypatch.setattr(main, "TURNSTILE_SECRET_KEY", "test-secret")
    monkeypatch.setattr(main, "TURNSTILE_EXPECTED_HOSTNAME", "app.example.test")
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["payload"] = req.data.decode("utf-8")
        captured["timeout"] = timeout
        return BytesIO(b'{"success":true,"hostname":"app.example.test","action":"auth"}')

    monkeypatch.setattr(main, "urlopen", fake_urlopen)
    main._verify_turnstile("valid-token", request_with_headers({"CF-Connecting-IP": "198.51.100.2"}), "auth")
    assert captured["url"].endswith("/siteverify")
    assert '"response": "valid-token"' in captured["payload"]
    assert '"remoteip": "198.51.100.2"' in captured["payload"]
    assert captured["timeout"] == 6


def test_turnstile_rejects_hostname_mismatch(monkeypatch):
    monkeypatch.setattr(main, "TURNSTILE_SECRET_KEY", "test-secret")
    monkeypatch.setattr(main, "TURNSTILE_EXPECTED_HOSTNAME", "expected.example.test")
    monkeypatch.setattr(main, "urlopen", lambda req, timeout: BytesIO(b'{"success":true,"hostname":"other.example.test","action":"auth"}'))
    with pytest.raises(HTTPException) as error:
        main._verify_turnstile("valid-token", request_with_headers(), "auth")
    assert error.value.status_code == 400
    assert "hostname" in error.value.detail.lower()


def test_turnstile_rejects_action_mismatch(monkeypatch):
    monkeypatch.setattr(main, "TURNSTILE_SECRET_KEY", "test-secret")
    monkeypatch.setattr(main, "TURNSTILE_EXPECTED_HOSTNAME", "")
    monkeypatch.setattr(main, "urlopen", lambda req, timeout: BytesIO(b'{"success":true,"hostname":"app.example.test","action":"signup"}'))
    with pytest.raises(HTTPException) as error:
        main._verify_turnstile("valid-token", request_with_headers(), "auth")
    assert error.value.status_code == 400
    assert "action" in error.value.detail.lower()


def test_turnstile_rejects_response_without_action(monkeypatch):
    monkeypatch.setattr(main, "TURNSTILE_SECRET_KEY", "test-secret")
    monkeypatch.setattr(main, "TURNSTILE_EXPECTED_HOSTNAME", "")
    monkeypatch.setattr(main, "urlopen", lambda req, timeout: BytesIO(b'{"success":true,"hostname":"app.example.test"}'))
    with pytest.raises(HTTPException) as error:
        main._verify_turnstile("valid-token", request_with_headers(), "auth")
    assert error.value.status_code == 400
    assert "action" in error.value.detail.lower()


def test_origin_lock_rejects_direct_api_bypass(monkeypatch):
    import asyncio

    from starlette.responses import Response

    monkeypatch.setattr(main, "CLOUDFLARE_EDGE_ENABLED", True)
    monkeypatch.setattr(main, "CLOUDFLARE_ORIGIN_SHARED_SECRET", "long-random-edge-secret")

    async def invoke(headers):
        reached = False

        async def call_next(_request):
            nonlocal reached
            reached = True
            return Response("ok", status_code=200)

        response = await main.security_headers_and_request_id(request_with_headers(headers), call_next)
        return response, reached

    blocked, reached = asyncio.run(invoke({}))
    assert blocked.status_code == 403
    assert not reached

    allowed, reached = asyncio.run(invoke({"X-ContexA-Origin-Secret": "long-random-edge-secret"}))
    assert allowed.status_code == 200
    assert reached
