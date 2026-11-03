from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    import hashlib
    import app.main as main_module
    from app.database import SessionLocal
    from app.models import LoginAttempt

    main_module.SIGNUP_MAX_PER_IP = 1000
    signup_key = hashlib.sha256(b"signup|testclient").hexdigest()
    with TestClient(app) as value:
        with SessionLocal() as db:
            db.query(LoginAttempt).filter(LoginAttempt.identity_hash == signup_key).delete(synchronize_session=False)
            db.commit()
        yield value


def register_workspace(client: TestClient) -> dict[str, str]:
    email = f"trust-os-{uuid.uuid4().hex[:12]}@example.test"
    response = client.post("/api/auth/register", json={
        "name": "Trust OS Owner", "email": email,
        "password": "TrustOS-Safe-Password-42", "workspace_name": "Trust OS Test Lab"})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def upload_text(client: TestClient, headers: dict[str, str], content: str):
    response = client.post("/api/documents/upload", headers=headers, files={
        "file": (f"trust-os-{uuid.uuid4().hex[:8]}.txt", content.encode("utf-8"), "text/plain")})
    assert response.status_code == 201, response.text
    return response.json()


def test_truth_drift_detects_change_and_opens_incident(client: TestClient, monkeypatch):
    import app.capabilities as capabilities

    headers = register_workspace(client)
    monkeypatch.setattr(capabilities, "_public_host", lambda _host: True)
    snapshots = iter([
        ("AstraTech Model A warranty: 2 years. Official product terms.", 200, "text/plain"),
        ("AstraTech Model A warranty: 1 year. Official product terms.", 200, "text/plain"),
    ])
    monkeypatch.setattr(capabilities, "_fetch_source", lambda _url: next(snapshots))

    created = client.post("/api/truth-drift/sources", headers=headers, json={
        "name": "AstraTech official specifications", "source_url": "https://example.test/specs",
        "authority": "Official product catalogue", "source_type": "official"})
    assert created.status_code == 201, created.text
    source_id = created.json()["id"]
    baseline = client.post(f"/api/truth-drift/sources/{source_id}/scan", headers=headers)
    assert baseline.status_code == 200 and baseline.json()["changed"] is False
    changed = client.post(f"/api/truth-drift/sources/{source_id}/scan", headers=headers)
    assert changed.status_code == 200 and changed.json()["changed"] is True
    assert changed.json()["event"]["severity"] == "medium"
    assert "review signal" in changed.json()["event"]["detail"].lower()
    assert changed.json()["incident"]["source_type"] == "truth_drift"
    events = client.get("/api/truth-drift/events", headers=headers)
    assert events.status_code == 200 and len(events.json()) == 1
    incidents = client.get("/api/incidents", headers=headers)
    assert incidents.status_code == 200 and any(x["source_type"] == "truth_drift" for x in incidents.json())


def test_passport_has_public_verification_record_and_revocation(client: TestClient):
    headers = register_workspace(client)
    doc = upload_text(client, headers,
        "AstraTech Model A product information. This document describes model features and warranty terms for review.")
    # Publish is a recorded governance transition. Any open critical finding must first be handled.
    detail = client.get(f"/api/documents/{doc['id']}", headers=headers)
    assert detail.status_code == 200, detail.text
    for finding in detail.json().get("findings", []):
        if finding.get("severity") == "critical" and finding.get("status") == "open":
            handled = client.post(f"/api/findings/{finding['id']}/action", headers=headers,
                json={"status": "dismissed", "note": "Reviewed against the approved internal evidence pack."})
            assert handled.status_code == 200, handled.text
    published = client.post(f"/api/documents/{doc['id']}/publish", headers=headers,
        json={"override_note": "Authorized demo sign-off after review."})
    assert published.status_code == 200, published.text
    issued = client.post("/api/trust-passports", headers=headers, json={
        "document_id": doc["id"], "title": "AstraTech Model A approved campaign", "include_public_claims": False})
    assert issued.status_code == 201, issued.text
    passport = issued.json()
    public = client.get(f"/api/public/trust-passports/{passport['public_id']}")
    assert public.status_code == 200, public.text
    assert public.json()["verified"] is True
    assert public.json()["signature_valid"] is True
    assert public.json()["asset_sha256"] == passport["asset_sha256"]
    assert public.json()["signed_manifest"]["public_claims_enabled"] is False
    assert public.json()["signature"]["manifest_sha256"]
    assert "does not independently prove" in public.json()["notice"]

    revoked = client.post(f"/api/trust-passports/{passport['id']}/revoke", headers=headers)
    assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"
    public_after_revoke = client.get(f"/api/public/trust-passports/{passport['public_id']}")
    assert public_after_revoke.status_code == 200
    assert public_after_revoke.json()["verified"] is False
    assert public_after_revoke.json()["status"] == "revoked"


def test_multimodal_text_inspection_persists_extraction_and_notice(client: TestClient):
    headers = register_workspace(client)
    payload = b"AstraTech campaign copy. Product warranty: 2 years. Please verify all approved claims."
    response = client.post("/api/multimodal/inspect", headers=headers, files={
        "file": ("campaign-copy.txt", payload, "text/plain")})
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["media_type"] == "document"
    assert data["sha256"] and len(data["sha256"]) == 64
    assert "warranty" in data["extracted_text"].lower()
    assert data["capability_status"]["ocr"] in {"extracted", "no_text_detected"}
    assert "screening signals" in data["review_notice"]
    history = client.get("/api/multimodal/inspections", headers=headers)
    assert history.status_code == 200 and any(item["id"] == data["id"] for item in history.json())


def test_multimodal_inspection_has_per_user_persistent_rate_limit(client: TestClient, monkeypatch):
    import app.capabilities as capabilities

    headers = register_workspace(client)
    monkeypatch.setattr(capabilities, "UPLOAD_MAX_PER_USER", 1)
    monkeypatch.setattr(capabilities, "UPLOAD_WINDOW_MINUTES", 60)
    first = client.post("/api/multimodal/inspect", headers=headers, files={
        "file": ("first.txt", b"A small approved sample document.", "text/plain")})
    assert first.status_code == 201, first.text
    second = client.post("/api/multimodal/inspect", headers=headers, files={
        "file": ("second.txt", b"A second sample document.", "text/plain")})
    assert second.status_code == 429, second.text


def test_governance_agents_are_deterministic_and_never_publish(client: TestClient):
    headers = register_workspace(client)
    response = client.post("/api/agents/runs", headers=headers, json={
        "objective": "Check campaign claims", "content_text": "Our platform is the #1 fastest and guarantees 40% revenue growth."})
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["status"] == "completed"
    assert data["outputs"]["risk_score_type"] == "deterministic_triage_not_probability"
    assert data["outputs"]["requires_human_review"] is True
    assert any(step["agent"] == "Approval Agent" for step in data["steps"])
    assert "do not have authority to approve or publish" in data["note"]
    history = client.get("/api/agents/runs", headers=headers)
    assert history.status_code == 200 and any(row["id"] == data["id"] for row in history.json())


def test_digital_twin_simulation_is_non_destructive_and_lists_affected_documents(client: TestClient):
    headers = register_workspace(client)
    doc = upload_text(client, headers,
        "AstraTech Model A includes a two-year warranty. Contact support for the approved terms.")
    response = client.post("/api/digital-twin/simulate", headers=headers, json={
        "name": "Warranty reduction impact", "scenario_type": "policy_change",
        "proposed_changes": {"pattern": "two-year warranty"}})
    assert response.status_code == 201, response.text
    report = response.json()
    assert report["documents_scanned"] >= 1
    assert report["documents_potentially_affected"] >= 1
    assert any(item["document_id"] == doc["id"] for item in report["affected_documents"])
    assert report["applied"] is False
    assert "stored extracted text" in report["limitation"]
    history = client.get("/api/digital-twin/scenarios", headers=headers)
    assert history.status_code == 200 and any(item["id"] == report["id"] for item in history.json())


def test_indic_regulatory_and_incident_lifecycle(client: TestClient):
    headers = register_workspace(client)
    indic = client.post("/api/indic/review", headers=headers, json={
        "language": "Marathi", "source_text": "Our product includes a 2-year warranty. #ad",
        "localized_text": "आमच्या उत्पादनात १ वर्षाची वॉरंटी आहे."})
    assert indic.status_code == 201, indic.text
    codes = {item["code"] for item in indic.json()["checks"]}
    assert "NUMERIC_PARITY" in codes
    assert "DISCLOSURE_AD" in codes
    assert indic.json()["status"] == "human_review_required"

    # Bengali digits and an equivalent configured local ad-disclosure term are recognized.
    bengali = client.post("/api/indic/review", headers=headers, json={
        "language": "Bengali", "source_text": "Our plan lasts 2 years. #ad",
        "localized_text": "আমাদের পরিকল্পনা ২ বছর। বিজ্ঞাপন"})
    assert bengali.status_code == 201, bengali.text
    parity = next(check for check in bengali.json()["checks"] if check["code"] == "NUMERIC_PARITY")
    assert parity["status"] == "matched"
    assert not any(check["code"] == "DISCLOSURE_AD" for check in bengali.json()["checks"])

    requirements = client.get("/api/regulatory/requirements", headers=headers)
    assert requirements.status_code == 200
    assert any(item["jurisdiction"] == "India" for item in requirements.json())
    assessment = client.post("/api/regulatory/assess", json={"content_text": "Influencer testimonial for a gifted product without an ad disclosure"}, headers=headers)
    assert assessment.status_code == 200, assessment.text
    assert assessment.json()["requirements_checked"] >= 3
    assert "not legal advice" in assessment.json()["notice"].lower()

    opened = client.post("/api/incidents", headers=headers, json={
        "title": "Unapproved campaign claim", "description": "A published campaign may contain an outdated product statement.",
        "severity": "high", "source_type": "manual", "affected_document_ids": []})
    assert opened.status_code == 201, opened.text
    incident_id = opened.json()["id"]
    acknowledged = client.patch(f"/api/incidents/{incident_id}", headers=headers,
        json={"status": "investigating", "note": "Evidence collection started."})
    assert acknowledged.status_code == 200 and acknowledged.json()["status"] == "investigating"
    invalid_resolution = client.patch(f"/api/incidents/{incident_id}", headers=headers,
        json={"status": "resolved"})
    assert invalid_resolution.status_code == 422
    resolved = client.patch(f"/api/incidents/{incident_id}", headers=headers,
        json={"status": "resolved", "resolution": "Campaign corrected and re-reviewed."})
    assert resolved.status_code == 200 and resolved.json()["status"] == "resolved"
    assert len(resolved.json()["timeline"]) >= 3


def test_trust_os_records_are_workspace_scoped(client: TestClient):
    owner = register_workspace(client)
    other = register_workspace(client)
    opened = client.post("/api/incidents", headers=owner, json={
        "title": "Tenant-bound incident", "description": "This incident must not cross tenant boundaries.",
        "severity": "medium", "source_type": "manual", "affected_document_ids": []})
    assert opened.status_code == 201
    assert client.get("/api/incidents", headers=other).json() == []
    assert client.get("/api/incidents", headers=owner).json()[0]["id"] == opened.json()["id"]
    denied = client.patch(f"/api/incidents/{opened.json()['id']}", headers=other,
        json={"status": "resolved", "resolution": "Not allowed"})
    assert denied.status_code == 404


def test_additive_migration_upgrades_existing_trust_os_database_and_backfills_passports():
    from datetime import datetime, timezone
    from sqlalchemy import MetaData, Table, Column, String, DateTime, create_engine, insert, inspect, select
    from sqlalchemy.orm import Session
    from app.database import Base, RLS_TABLES
    from app.migrations import run_migrations
    from app.models import User, ContentDocument, TrustPassport

    engine = create_engine("sqlite://")
    try:
        # Emulate a database where migration 01 is already applied but migration 02
        # (the RLS-safe public passport index) is missing.
        prior_tables = [table for table in Base.metadata.sorted_tables if table.name != "public_passport_index"]
        Base.metadata.create_all(engine, tables=prior_tables)
        migration_meta = MetaData()
        versions = Table("schema_migrations", migration_meta,
            Column("version", String(100), primary_key=True),
            Column("applied_at", DateTime(timezone=True), nullable=False))
        migration_meta.create_all(engine)
        workspace_id = "ws-migration-backfill"
        user_id = str(uuid.uuid4()); document_id = str(uuid.uuid4()); passport_id = str(uuid.uuid4())
        with Session(engine) as session:
            session.add(User(id=user_id, name="Migration Owner", email="migration@example.test", role="Brand Admin",
                workspace_id=workspace_id, workspace_name="Migration Test", password_hash="not-a-real-password"))
            session.flush()
            session.add(ContentDocument(id=document_id, workspace_id=workspace_id, filename="approved.txt",
                stored_path="private/approved.txt", content_type="text/plain", content_text="Approved asset",
                pages_json=[], page_count=1, status="PUBLISH_READY", compliance_score=100, size_bytes=14,
                sha256="a" * 64, scan_status="clean", created_by=user_id))
            session.flush()
            payload = {"schema": "contexa-trust-passport/1.0", "public_id": "b" * 32,
                "title": "Legacy approved asset", "asset_sha256": "a" * 64, "verification": {"publication_signoff": True}}
            session.add(TrustPassport(id=passport_id, workspace_id=workspace_id, document_id=document_id,
                public_id="b" * 32, title="Legacy approved asset", asset_sha256="a" * 64,
                payload=payload, signature="c" * 64, issued_by=user_id, status="active"))
            session.commit()
        with engine.begin() as connection:
            connection.execute(insert(versions).values(version="2026_11_01_01_trust_os_capabilities", applied_at=datetime.now(timezone.utc)))
        applied = run_migrations(engine)
        assert applied == ["2026_11_01_02_public_passport_index", "2026_11_01_03_enterprise_trust_foundation",
                           "2026_11_01_04_collaboration_analytics_indexes"]
        assert inspect(engine).has_table("public_passport_index")
        with engine.connect() as connection:
            public_row = connection.execute(select(Base.metadata.tables["public_passport_index"]).where(
                Base.metadata.tables["public_passport_index"].c.public_id == "b" * 32)).mappings().one()
        assert public_row["passport_id"] == passport_id
        assert public_row["status"] == "active"
        assert "public_passport_index" not in RLS_TABLES
        assert "passport_signatures" not in RLS_TABLES
        assert {"evidence_graph_nodes", "evidence_graph_edges", "decision_traces", "evidence_archives", "evidence_merkle_anchors"}.issubset(set(RLS_TABLES))
    finally:
        engine.dispose()


def test_source_monitor_rejects_private_and_link_local_dns_answers(monkeypatch):
    import app.capabilities as capabilities

    monkeypatch.setattr(capabilities.socket, "getaddrinfo", lambda *args, **kwargs: [
        (2, 1, 6, "", ("127.0.0.1", 443))])
    assert capabilities._public_host("rebind.example.test") is False
    with pytest.raises(ValueError, match="non-public"):
        capabilities._resolve_public_ip("rebind.example.test", 443)
