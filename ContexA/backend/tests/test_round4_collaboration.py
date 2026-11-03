from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.test_api_smoke import client as _client  # noqa: F401  (reuse module fixture)
from tests.test_api_smoke import login

client = _client


def _upload(client, headers, name="r4-claim.txt", text=b"We guarantee 400% growth, the #1 fastest platform ever."):
    r = client.post("/api/documents/upload", headers=headers, files={"file": (name, text, "text/plain")})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_request_id_and_health_endpoints(client: TestClient):
    r = client.get("/api/health/live", headers={"X-Request-ID": "abcdef1234567890"})
    assert r.status_code == 200 and r.headers["x-request-id"] == "abcdef1234567890"
    assert client.get("/api/health/live", headers={"X-Request-ID": "bad id!"}).headers["x-request-id"] != "bad id!"
    ready = client.get("/api/health/ready")
    assert ready.status_code == 200
    assert ready.json()["checks"]["database"] == "ok" and ready.json()["checks"]["migrations_applied"] >= 4
    assert client.get("/api/metrics").status_code == 404  # disabled without METRICS_TOKEN


def test_review_routing_creates_notifications_and_read_state(client: TestClient):
    admin = login(client, "admin@contexa.local", "ContexA!2026")
    legal = login(client, "legal@contexa.local", "Legal!2026")
    _upload(client, admin)
    inbox = client.get("/api/notifications", headers=legal).json()
    assert inbox["unread_count"] >= 1
    first = inbox["items"][0]
    assert first["kind"] == "review_task" and first["read"] is False
    # Another user can't read someone else's notification.
    assert client.post(f"/api/notifications/{first['id']}/read", headers=admin).status_code == 404
    assert client.post(f"/api/notifications/{first['id']}/read", headers=legal).json()["read"] is True
    all_read = client.post("/api/notifications/read-all", headers=legal).json()
    assert all_read["unread_count"] == 0
    assert client.get("/api/notifications/unread-count", headers=legal).json()["unread_count"] == 0


def test_comment_threads_mentions_permissions_and_search(client: TestClient):
    admin = login(client, "admin@contexa.local", "ContexA!2026")
    creator = login(client, "creator@contexa.local", "Creator!2026")
    manager = login(client, "manager@contexa.local", "Manager!2026")
    doc_id = _upload(client, admin, "r4-thread.txt")
    root = client.post("/api/comments", headers=admin, json={"entity_type": "document", "entity_id": doc_id,
        "body": "Please verify the growth claim @manager@contexa.local"})
    assert root.status_code == 201 and len(root.json()["mentions"]) == 1
    reply = client.post("/api/comments", headers=creator, json={"entity_type": "document", "entity_id": doc_id,
        "body": "Working on it.", "parent_id": root.json()["id"]})
    assert reply.status_code == 201
    nested = client.post("/api/comments", headers=creator, json={"entity_type": "document", "entity_id": doc_id,
        "body": "too deep", "parent_id": reply.json()["id"]})
    assert nested.status_code == 422
    threads = client.get("/api/comments", headers=admin, params={"entity_type": "document", "entity_id": doc_id}).json()
    assert threads["total"] == 2 and len(threads["threads"][0]["replies"]) == 1
    # Mention produced a notification for the manager.
    kinds = [n["kind"] for n in client.get("/api/notifications", headers=manager).json()["items"]]
    assert "mention" in kinds
    # Only the author edits; a creator can't resolve someone else's thread, a manager can.
    assert client.patch(f"/api/comments/{root.json()['id']}", headers=creator, json={"body": "hijack"}).status_code == 403
    assert client.patch(f"/api/comments/{root.json()['id']}", headers=creator, json={"resolved": True}).status_code == 403
    assert client.patch(f"/api/comments/{root.json()['id']}", headers=manager, json={"resolved": True}).json()["resolved"] is True
    # Search finds the document and the comment.
    found = client.get("/api/search", headers=admin, params={"q": "r4-thread"}).json()
    assert any(d["id"] == doc_id for d in found["results"]["documents"])
    found = client.get("/api/search", headers=admin, params={"q": "verify the growth"}).json()
    assert found["results"]["comments"]
    # Wildcard characters are escaped, not treated as match-all.
    assert client.get("/api/search", headers=admin, params={"q": "%%"}).json()["total"] == 0
    # Soft delete: creator can delete own reply, not admin's root.
    assert client.delete(f"/api/comments/{root.json()['id']}", headers=creator).status_code == 403
    assert client.delete(f"/api/comments/{reply.json()['id']}", headers=creator).status_code == 204
    assert client.post("/api/comments", headers=admin, json={"entity_type": "document", "entity_id": "nope", "body": "x"}).status_code == 404


def test_workspace_isolation_for_new_endpoints(client: TestClient):
    admin = login(client, "admin@contexa.local", "ContexA!2026")
    doc_id = _upload(client, admin, "r4-private.txt")
    reg = client.post("/api/auth/register", json={"name": "Other Tenant", "email": f"tenant-{__import__('uuid').uuid4().hex[:10]}@example.com",
                                                   "password": "Another-pass-2026"})
    assert reg.status_code == 201, reg.text
    other = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    assert client.get("/api/comments", headers=other, params={"entity_type": "document", "entity_id": doc_id}).status_code == 404
    assert client.get(f"/api/documents/{doc_id}/activity", headers=other).status_code == 404
    assert client.post("/api/comments", headers=other, json={"entity_type": "document", "entity_id": doc_id, "body": "hi"}).status_code == 404
    assert client.get("/api/search", headers=other, params={"q": "r4-private"}).json()["total"] == 0
    assert client.get("/api/notifications", headers=other).json()["total"] == 0


def test_activity_timeline_trend_and_workload(client: TestClient):
    admin = login(client, "admin@contexa.local", "ContexA!2026")
    doc_id = _upload(client, admin, "r4-activity.txt")
    events = client.get(f"/api/documents/{doc_id}/activity", headers=admin).json()["events"]
    assert any(e["action"] == "document.uploaded_and_scanned" for e in events)
    trend = client.get("/api/analytics/trend", headers=admin, params={"days": 7}).json()
    assert trend["series"] and trend["series"][-1]["total_documents"] >= 1
    assert trend["series"][-1]["critical_findings"] >= 1
    csv = client.get("/api/analytics/trend", headers=admin, params={"format": "csv"})
    assert csv.status_code == 200 and csv.text.startswith("date,integrity_score")
    creator = login(client, "creator@contexa.local", "Creator!2026")
    assert client.post("/api/analytics/snapshot", headers=creator).status_code == 403
    assert client.post("/api/analytics/snapshot", headers=admin).status_code == 200
    load = client.get("/api/analytics/workload", headers=admin).json()
    assert load["open_tasks"] >= 1 and load["by_assignee"]


def test_public_auth_config_reports_what_works(client: TestClient):
    cfg = client.get("/api/auth/config")
    assert cfg.status_code == 200
    body = cfg.json()
    assert body["local_login"] is True and body["signup_open"] is True
    assert body["demo_accounts"] is True  # APP_ENV=development in tests
    # Without SMTP, recovery is only offered because dev mode returns the link; never claim email delivery.
    assert body["recovery_delivery"] in {"email", "development_link"}
    assert "password" not in str(body).lower().replace("password_recovery", "")


def test_recovery_hidden_in_production_without_smtp(client: TestClient, monkeypatch):
    import app.config as config
    import app.main as main_module
    monkeypatch.setattr(config, "APP_ENV", "production")
    monkeypatch.setattr(main_module, "_smtp_ready", lambda: False)
    body = client.get("/api/auth/config").json()
    assert body["password_recovery"] is False and body["recovery_delivery"] == "none"
    assert body["demo_accounts"] is False
