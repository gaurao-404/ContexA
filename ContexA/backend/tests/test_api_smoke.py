from __future__ import annotations

import fitz
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    import hashlib
    import app.main as main_module
    from app.database import SessionLocal
    from app.models import LoginAttempt, User
    main_module.SIGNUP_MAX_PER_IP = 1000
    signup_key = hashlib.sha256(b"signup|testclient").hexdigest()
    # Startup creates/migrates tables. Enter TestClient before touching persistent
    # rate-limit rows so repeated local runs do not inherit stale test lockouts.
    with TestClient(app) as value:
        with SessionLocal() as db:
            db.query(LoginAttempt).filter(LoginAttempt.identity_hash == signup_key).delete(synchronize_session=False)
            # These smoke tests use the seeded demo administrator for uploads. Clear
            # only that test identity's upload throttle; never weaken runtime limits.
            admin = db.query(User).filter(User.email == "admin@contexa.local").first()
            if admin:
                upload_key = main_module._auth_digest(f"upload-user|{admin.id}")
                db.query(LoginAttempt).filter(LoginAttempt.identity_hash == upload_key).delete(synchronize_session=False)
            db.commit()
        yield value


def login(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_upload_review_gate_revision_export_and_audit(client: TestClient):
    admin = login(client, "admin@contexa.local", "ContexA!2026")
    creator = login(client, "creator@contexa.local", "Creator!2026")
    upload = client.post("/api/documents/upload", headers=admin, files={
        "file": ("proof-claim.txt", b"Contexa says we are the #1 fastest platform to boost revenue by 400%.", "text/plain")
    })
    assert upload.status_code == 201, upload.text
    doc_id = upload.json()["id"]
    detail = client.get(f"/api/documents/{doc_id}", headers=admin)
    assert detail.status_code == 200
    findings = detail.json()["findings"]
    assert {f["rule_code"] for f in findings} >= {"CLM-204", "LGL-002"}
    critical = [f for f in findings if f["severity"] == "critical"]
    assert len(critical) >= 1

    forbidden = client.post(f"/api/findings/{critical[0]['id']}/action", headers=creator,
        json={"status": "accepted"})
    assert forbidden.status_code == 403

    # An attempted edit without exact replacement copy is rejected.
    warning = next(f for f in findings if f["rule_code"] == "TERM-008")
    invalid_edit = client.post(f"/api/findings/{warning['id']}/action", headers=admin,
        json={"status": "edited"})
    assert invalid_edit.status_code == 422
    revised = client.post(f"/api/findings/{warning['id']}/action", headers=admin,
        json={"status": "edited", "note": "Reviewed revised copy", "applied_text": "ContexA is designed to help teams review approved brand content."})
    assert revised.status_code == 200, revised.text
    assert revised.json()["finding"]["applied_text"].startswith("ContexA is designed")

    for finding in critical:
        res = client.post(f"/api/findings/{finding['id']}/action", headers=admin,
            json={"status": "dismissed", "note": "Legal approved this statement for the internal demo."})
        assert res.status_code == 200, res.text
    blocked = client.post(f"/api/documents/{doc_id}/publish", headers=admin, json={"override_note": ""})
    assert blocked.status_code == 422
    approved = client.post(f"/api/documents/{doc_id}/publish", headers=admin,
        json={"override_note": "Legal reviewer accepted the documented exceptions for demo purposes."})
    assert approved.status_code == 200, approved.text
    assert approved.json()["document"]["status"] == "PUBLISH_READY"

    export = client.get(f"/api/documents/{doc_id}/export?fmt=csv", headers=admin)
    assert export.status_code == 200 and "applied_text" in export.text
    audit = client.get("/api/audit?limit=30", headers=admin)
    assert audit.status_code == 200
    assert any(item["action"] == "document.publish_ready" for item in audit.json())


def test_pdf_preview_is_real_rendered_content(client: TestClient):
    admin = login(client, "admin@contexa.local", "ContexA!2026")
    pdf = fitz.open()
    page = pdf.new_page(width=612, height=792)
    page.insert_text((55, 90), "The #1 fastest platform to boost revenue by 400%.", fontsize=16, color=(0.78, 0.78, 0.78))
    payload = pdf.tobytes()
    pdf.close()
    upload = client.post("/api/documents/upload", headers=admin,
        files={"file": ("sample.pdf", payload, "application/pdf")})
    assert upload.status_code == 201, upload.text
    doc_id = upload.json()["id"]
    preview = client.get(f"/api/documents/{doc_id}/preview/1", headers=admin)
    assert preview.status_code == 200, preview.text[:200]
    assert preview.headers["content-type"].startswith("image/png")
    assert preview.content.startswith(b"\x89PNG")


def test_write_time_copy_check_uses_approved_workspace_rules(client: TestClient):
    admin = login(client, "admin@contexa.local", "ContexA!2026")
    response = client.post("/api/check-copy", headers=admin, json={
        "text": "Contexa is the #1 fastest platform to boost revenue by 400%. Our revolutionary plan is only $19/month — save 30% today!"
    })
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["mode"] == "deterministic"
    assert payload["findings_count"] >= 4
    codes = {finding["rule_code"] for finding in payload["findings"]}
    assert {"CLM-204", "LGL-002", "TERM-001", "TERM-008", "PRC-002"}.issubset(codes)
    assert "cannot determine freshness" in next(f["suggested_fix"] for f in payload["findings"] if f["rule_code"] == "PRC-002")


def test_pptx_upload_flags_picture_with_filename_only_alt_text(client: TestClient):
    from io import BytesIO
    from pptx import Presentation
    from pptx.util import Inches
    from PIL import Image

    admin = login(client, "admin@contexa.local", "ContexA!2026")
    image = BytesIO(); Image.new("RGB", (32, 32), color=(117, 88, 238)).save(image, format="PNG"); image.seek(0)
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    slide.shapes.add_picture(image, Inches(1), Inches(1), width=Inches(1), height=Inches(1))
    output = BytesIO(); presentation.save(output)
    uploaded = client.post("/api/documents/upload", headers=admin,
        files={"file": ("campaign-slide.pptx", output.getvalue(), "application/vnd.openxmlformats-officedocument.presentationml.presentation")})
    assert uploaded.status_code == 201, uploaded.text
    detail = client.get(f"/api/documents/{uploaded.json()['id']}", headers=admin)
    assert detail.status_code == 200
    accessibility = [f for f in detail.json()["findings"] if f.get("rule_code") == "A11Y-001"]
    assert accessibility, "Expected a verified missing/meaningless alt-text finding for the PowerPoint picture."


def test_guideline_import_creates_paused_reviewable_rules(client: TestClient):
    admin = login(client, "admin@contexa.local", "ContexA!2026")
    creator = login(client, "creator@contexa.local", "Creator!2026")
    denied = client.post("/api/guidelines/import", headers=creator,
        files={"file": ("guide.txt", b"Always support quantified claims with evidence before publication.", "text/plain")})
    assert denied.status_code == 403

    source = (b"Never use world-class in marketing copy.\n"
              b"Pricing must match the current approved price book and campaign validity window.\n"
              b"Claims about performance or revenue require evidence and legal review before publication.\n")
    response = client.post("/api/guidelines/import", headers=admin,
        files={"file": ("brand-policy.txt", source, "text/plain")})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["created_rules"] == 3
    assert all(not rule["is_active"] for rule in payload["rules"])
    rules = client.get("/api/rules?q=brand-policy.txt", headers=admin)
    imported = [rule for rule in rules.json() if rule["id"] in {candidate["id"] for candidate in payload["rules"]}]
    assert len(imported) == 3
    assert all(rule["is_active"] is False for rule in imported)
    assert any(rule["pattern"] for rule in imported), "Simple explicit prohibitions should yield a reviewable deterministic pattern candidate."


def test_demo_seed_is_repeatable_and_does_not_require_local_ai(client: TestClient):
    admin = login(client, "admin@contexa.local", "ContexA!2026")
    creator = login(client, "creator@contexa.local", "Creator!2026")
    denied = client.post("/api/demo/seed", headers=creator)
    assert denied.status_code == 403

    first = client.post("/api/demo/seed", headers=admin)
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["ai_mode"] == "deterministic_only"
    assert len(payload["documents"]) == 3
    assert "No Ollama request" in payload["notice"]
    assert {doc["filename"] for doc in payload["documents"]} >= {
        "DEMO_Q4_Launch_Campaign.txt", "DEMO_Product_Naming_Review.txt", "DEMO_Pricing_Refresh.txt"
    }

    second = client.post("/api/demo/seed", headers=admin)
    assert second.status_code == 200, second.text
    assert second.json()["created_documents"] == 0
    assert len(second.json()["documents"]) == 3


def test_self_service_registration_creates_isolated_workspace(client: TestClient):
    import uuid

    email = f"new-account-{uuid.uuid4().hex[:10]}@example.test"
    response = client.post("/api/auth/register", json={
        "name": "New Workspace Owner",
        "email": email,
        "password": "well-made-password-42",
        "workspace_name": "Northstar Creative",
    })
    assert response.status_code == 201, response.text
    payload = response.json()
    account = payload["user"]
    assert payload["access_token"]
    assert account["email"] == email
    assert account["role"] == "Brand Admin"
    assert account["workspace_name"] == "Northstar Creative"
    assert account["workspace_id"].startswith("ws-")

    new_workspace_headers = {"Authorization": f"Bearer {payload['access_token']}"}
    rules = client.get("/api/rules", headers=new_workspace_headers)
    assert rules.status_code == 200
    assert {rule["code"] for rule in rules.json()} >= {"CLM-204", "TERM-008", "PRC-002"}

    admin = login(client, "admin@contexa.local", "ContexA!2026")
    assert client.get("/api/settings", headers=admin).json()["workspace"]["id"] != account["workspace_id"]

    upload = client.post("/api/documents/upload", headers=new_workspace_headers,
        files={"file": ("private-campaign.txt", b"Northstar is the #1 fastest platform.", "text/plain")})
    assert upload.status_code == 201, upload.text
    doc_id = upload.json()["id"]
    # The second workspace must neither list nor fetch the new account's document.
    admin_docs = client.get("/api/documents", headers=admin)
    assert admin_docs.status_code == 200
    assert all(doc["id"] != doc_id for doc in admin_docs.json())
    assert client.get(f"/api/documents/{doc_id}", headers=admin).status_code == 404

    duplicate = client.post("/api/auth/register", json={
        "name": "Duplicate Email", "email": email.upper(),
        "password": "well-made-password-42", "workspace_name": "Another Workspace"})
    assert duplicate.status_code == 409


def test_self_service_registration_rejects_weak_password(client: TestClient):
    response = client.post("/api/auth/register", json={
        "name": "Weak Password Test", "email": "weak-password@example.test", "password": "short"})
    assert response.status_code == 422


def test_upload_binary_can_be_previewed_after_ephemeral_file_disappears(client: TestClient, monkeypatch):
    import app.main as main_module
    from pathlib import Path

    monkeypatch.setattr(main_module, "STORE_UPLOADS_IN_DATABASE", True)
    admin = login(client, "admin@contexa.local", "ContexA!2026")
    pdf = fitz.open()
    page = pdf.new_page(width=612, height=792)
    page.insert_text((55, 90), "A claim requiring evidence.", fontsize=16)
    payload = pdf.tobytes()
    pdf.close()
    uploaded = client.post("/api/documents/upload", headers=admin,
        files={"file": ("persistent.pdf", payload, "application/pdf")})
    assert uploaded.status_code == 201, uploaded.text
    doc_id = uploaded.json()["id"]
    with main_module.SessionLocal() as db:
        doc = db.get(main_module.ContentDocument, doc_id)
        assert doc is not None and doc.file_data == payload
        Path(doc.stored_path).unlink(missing_ok=True)
    preview = client.get(f"/api/documents/{doc_id}/preview/1", headers=admin)
    assert preview.status_code == 200, preview.text[:200]
    assert preview.content.startswith(b"\x89PNG")


def test_security_headers_and_request_id_are_present(client: TestClient):
    response = client.get("/api/health", headers={"X-Request-ID": "round3-test-123"})
    assert response.status_code == 200
    assert response.headers["x-request-id"] == "round3-test-123"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_logout_revokes_previously_issued_access_tokens(client: TestClient):
    admin = login(client, "admin@contexa.local", "ContexA!2026")
    me_before = client.get("/api/auth/me", headers=admin)
    assert me_before.status_code == 200
    logged_out = client.post("/api/auth/logout", headers=admin)
    assert logged_out.status_code == 200
    rejected = client.get("/api/auth/me", headers=admin)
    assert rejected.status_code == 401
    assert "revoked" in rejected.json()["detail"].lower()


def test_supabase_only_mode_blocks_local_password_onboarding(client: TestClient, monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "AUTH_MODE", "supabase")
    register = client.post("/api/auth/register", json={
        "name": "Unexpected Local User", "email": "local-path@example.test",
        "password": "Long-Enough-Password-2026", "workspace_name": "Unprovisioned Workspace"})
    assert register.status_code == 403
    login_response = client.post("/api/auth/login", json={
        "email": "admin@contexa.local", "password": "ContexA!2026"})
    assert login_response.status_code == 403
    forgot = client.post("/api/auth/password/forgot", json={"email": "admin@example.test"})
    assert forgot.status_code == 403
    reset = client.post("/api/auth/password/reset", json={
        "token": "x" * 32, "password": "Long-Enough-Password-2026"})
    assert reset.status_code == 403


def test_health_is_database_readiness_and_csp_uses_configured_origins(client: TestClient, monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "SUPABASE_URL", "https://tenant-example.supabase.co")
    monkeypatch.setattr(main_module, "PUBLIC_API_URL", "https://api.example.test")
    monkeypatch.setattr(main_module, "CSP_EXTRA_CONNECT_ORIGINS", "https://events.example.test,https://ignored.example.test/path")
    response = client.get("/api/health")
    assert response.status_code == 200, response.text
    assert response.json()["database_ready"] is True
    policy = response.headers["content-security-policy"]
    assert "https://tenant-example.supabase.co" in policy
    assert "https://api.example.test" in policy
    assert "https://events.example.test" in policy
    assert "https://ignored.example.test/path" not in policy


def test_health_returns_503_when_database_is_unavailable(client: TestClient, monkeypatch):
    import app.main as main_module

    def unavailable():
        raise OSError("simulated database outage")

    monkeypatch.setattr(main_module.engine, "connect", unavailable)
    response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json()["detail"] == "Application database is unavailable."


def test_supabase_jwt_algorithm_configuration_rejects_shared_secret(monkeypatch):
    import app.security as security
    from fastapi import HTTPException

    monkeypatch.setattr(security, "SUPABASE_JWT_ALGORITHMS", ["HS256"])
    monkeypatch.setattr(security, "SUPABASE_JWKS_URL", "https://tenant.example.supabase.co/auth/v1/.well-known/jwks.json")
    monkeypatch.setattr(security, "SUPABASE_JWT_ISSUER", "https://tenant.example.supabase.co/auth/v1")
    with pytest.raises(HTTPException) as error:
        security.decode_supabase_access_token("header.payload.signature")
    assert error.value.status_code == 503


def test_production_cors_origins_require_exact_https_frontends(monkeypatch):
    import app.main as main_module
    from app.main import _validate_production_cors_origins

    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    with pytest.raises(RuntimeError, match="ALLOWED_ORIGINS"):
        _validate_production_cors_origins()

    monkeypatch.setenv("ALLOWED_ORIGINS", "https://app.example.test,https://admin.example.test")
    _validate_production_cors_origins()

    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:5173")
    with pytest.raises(RuntimeError, match="exact HTTPS"):
        _validate_production_cors_origins()

    monkeypatch.setenv("ALLOWED_ORIGINS", "https://app.example.test/workspace")
    with pytest.raises(RuntimeError, match="exact HTTPS"):
        _validate_production_cors_origins()


def test_supabase_production_mode_fails_closed_without_session_reader(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "AUTH_MODE", "supabase")
    monkeypatch.setattr(main_module, "SUPABASE_URL", "https://tenant.example.supabase.co")
    monkeypatch.setattr(main_module, "SUPABASE_JWT_ISSUER", "https://tenant.example.supabase.co/auth/v1")
    monkeypatch.setattr(main_module, "SUPABASE_JWKS_URL", "https://tenant.example.supabase.co/auth/v1/.well-known/jwks.json")
    monkeypatch.setattr(main_module, "SUPABASE_JWT_ALGORITHMS", ["ES256"])
    monkeypatch.setattr(main_module, "SUPABASE_SESSION_CHECK_REQUIRED", True)
    monkeypatch.setattr(main_module, "SUPABASE_SESSION_DATABASE_URL", "")
    monkeypatch.setattr(main_module, "SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")
    with pytest.raises(RuntimeError, match="SUPABASE_SESSION_DATABASE_URL"):
        main_module.startup()


def test_supabase_mode_fails_closed_without_publishable_key_for_logout(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "AUTH_MODE", "supabase")
    monkeypatch.setattr(main_module, "SUPABASE_URL", "https://tenant.example.supabase.co")
    monkeypatch.setattr(main_module, "SUPABASE_JWT_ISSUER", "https://tenant.example.supabase.co/auth/v1")
    monkeypatch.setattr(main_module, "SUPABASE_JWKS_URL", "https://tenant.example.supabase.co/auth/v1/.well-known/jwks.json")
    monkeypatch.setattr(main_module, "SUPABASE_JWT_ALGORITHMS", ["ES256"])
    monkeypatch.setattr(main_module, "SUPABASE_SESSION_CHECK_REQUIRED", True)
    monkeypatch.setattr(main_module, "SUPABASE_SESSION_DATABASE_URL", "postgresql+psycopg://reader:secret@host/postgres")
    monkeypatch.setattr(main_module, "SUPABASE_PUBLISHABLE_KEY", "")
    with pytest.raises(RuntimeError, match="SUPABASE_PUBLISHABLE_KEY"):
        main_module.startup()
