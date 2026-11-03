from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    # Keep suite-level account-creation tests independent of persistent local test state.
    import hashlib
    import app.main as main_module
    from app.database import SessionLocal
    from app.models import LoginAttempt
    main_module.SIGNUP_MAX_PER_IP = 1000
    signup_key = hashlib.sha256(b"signup|testclient").hexdigest()
    # Startup creates/migrates tables. Enter TestClient before touching persistent
    # rate-limit rows so a clean checkout can run the suite without a pre-existing DB.
    with TestClient(app) as value:
        with SessionLocal() as db:
            db.query(LoginAttempt).filter(LoginAttempt.identity_hash == signup_key).delete(synchronize_session=False)
            db.commit()
        yield value


def register_workspace(client: TestClient) -> dict[str, str]:
    email = f"round3-{uuid.uuid4().hex[:10]}@example.test"
    response = client.post("/api/auth/register", json={
        "name": "Round Three Owner", "email": email,
        "password": "RoundThree-Safe-Password-42", "workspace_name": "Round Three Lab"})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_fact_truth_engine_approves_and_flags_price_mismatch(client: TestClient):
    headers = register_workspace(client)
    created = client.post("/api/facts", headers=headers, json={
        "fact_key": "contexa.pro.monthly_price", "fact_type": "price",
        "entity_name": "ContexA Pro", "canonical_value": "₹54,999/month",
        "currency": "INR", "unit": "per month",
        "source_document": "Approved FY27 Price Book",
        "source_quote": "ContexA Pro subscription is ₹54,999 per month, effective 1 October.",
    })
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "draft"
    approved = client.post(f"/api/facts/{created.json()['id']}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    uploaded = client.post("/api/documents/upload", headers=headers, files={
        "file": ("pricing-draft.txt", "The ContexA Pro plan is available for ₹49,999/month.".encode(), "text/plain")})
    assert uploaded.status_code == 201, uploaded.text
    detail = client.get(f"/api/documents/{uploaded.json()['id']}", headers=headers)
    assert detail.status_code == 200, detail.text
    mismatch = [f for f in detail.json()["findings"] if "does not match the current approved price fact" in f["reasoning"]]
    assert mismatch, detail.json()["findings"]
    evidence = client.get(f"/api/findings/{mismatch[0]['id']}/evidence", headers=headers)
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["evidence"][0]["source_kind"] == "approved_fact"
    assert evidence.json()["evidence"][0]["source_quote"].startswith("ContexA Pro subscription")


def test_findings_store_rule_version_evidence_and_scan_runs(client: TestClient):
    headers = register_workspace(client)
    uploaded = client.post("/api/documents/upload", headers=headers, files={
        "file": ("claim.txt", b"We are the #1 fastest platform to increase revenue by 400%.", "text/plain")})
    assert uploaded.status_code == 201, uploaded.text
    detail = client.get(f"/api/documents/{uploaded.json()['id']}", headers=headers).json()
    claim = next(f for f in detail["findings"] if f["rule_code"] == "CLM-204")
    assert claim["rule_version_id"]
    evidence = client.get(f"/api/findings/{claim['id']}/evidence", headers=headers).json()
    assert evidence["evidence"]
    assert evidence["evidence"][0]["source_kind"] == "brand_rule"
    assert evidence["evidence"][0]["verification_status"] == "grounded"
    scans = client.get(f"/api/scans?document_id={uploaded.json()['id']}", headers=headers)
    assert scans.status_code == 200 and len(scans.json()) == 1
    assert scans.json()[0]["total_findings"] >= 2
    tasks = client.get("/api/review-tasks", headers=headers)
    assert tasks.status_code == 200
    assert any(task["assigned_role"] == "SME / Legal" for task in tasks.json())


def test_policy_simulation_is_non_destructive_until_applied(client: TestClient):
    headers = register_workspace(client)
    uploaded = client.post("/api/documents/upload", headers=headers, files={
        "file": ("draft.txt", b"This is our best platform. It is very fast.", "text/plain")})
    assert uploaded.status_code == 201
    rules = client.get("/api/rules", headers=headers).json()
    rule = next(item for item in rules if item["code"] == "TERM-001")
    simulated = client.post("/api/policy-simulations", headers=headers, json={
        "rule_id": rule["id"], "proposed_pattern": r"\bbest\b|\bfast\b"})
    assert simulated.status_code == 200, simulated.text
    assert simulated.json()["documents_affected"] == 1
    history = client.get("/api/policy-simulations", headers=headers)
    assert history.status_code == 200 and history.json()
    applied = client.post(f"/api/policy-simulations/{simulated.json()['id']}/apply", headers=headers,
        json={"change_note": "Expanded terminology coverage after impact simulation."})
    assert applied.status_code == 200, applied.text
    assert applied.json()["version"] >= 2


def test_evaluation_benchmark_and_brand_intelligence(client: TestClient):
    headers = register_workspace(client)
    seeded = client.post("/api/evaluation/seed", headers=headers)
    assert seeded.status_code == 200, seeded.text
    assert seeded.json()["total"] >= 50
    run = client.post("/api/evaluation/run", headers=headers)
    assert run.status_code == 200, run.text
    result = run.json()
    assert result["case_count"] == 50
    assert result["false_positives"] == 0
    assert result["false_negatives"] == 0
    assert result["precision"] == 1.0
    assert 0 <= result["recall"] <= 1
    assert 0 <= result["f1_score"] <= 1
    intelligence = client.get("/api/brand-intelligence", headers=headers)
    assert intelligence.status_code == 200, intelligence.text
    assert intelligence.json()["latest_evaluation"]["case_count"] == 50


def test_workspace_isolation_for_facts_and_rule_history(client: TestClient):
    owner_headers = register_workspace(client)
    other_headers = register_workspace(client)
    created = client.post("/api/facts", headers=owner_headers, json={
        "fact_key": "private.price", "fact_type": "price", "entity_name": "Private Plan",
        "canonical_value": "INR 9,999", "source_document": "Private source",
        "source_quote": "Private approved price is INR 9,999 per month."})
    assert created.status_code == 201
    owner_facts = client.get("/api/facts", headers=owner_headers).json()
    other_facts = client.get("/api/facts", headers=other_headers).json()
    assert any(item["id"] == created.json()["id"] for item in owner_facts)
    assert all(item["id"] != created.json()["id"] for item in other_facts)

    owner_rules = client.get("/api/rules", headers=owner_headers).json()
    owner_rule = next(item for item in owner_rules if item["code"] == "TERM-001")
    forbidden = client.get(f"/api/rules/{owner_rule['id']}/versions", headers=other_headers)
    assert forbidden.status_code == 404


def test_fact_source_quote_can_be_verified_against_workspace_document(client: TestClient):
    headers = register_workspace(client)
    source_text = b"Approved price book: ContexA Pro monthly subscription is INR 54,999, effective 1 October 2026."
    source = client.post("/api/documents/upload", headers=headers, files={
        "file": ("approved-price-book.txt", source_text, "text/plain")})
    assert source.status_code == 201, source.text
    bad = client.post("/api/facts", headers=headers, json={
        "fact_key": "pro.monthly", "fact_type": "price", "entity_name": "ContexA Pro",
        "canonical_value": "INR 54,999/month", "source_document": "approved-price-book.txt",
        "source_quote": "ContexA Pro costs INR 12,000 per month.",
        "source_document_id": source.json()["id"]})
    assert bad.status_code == 422
    good = client.post("/api/facts", headers=headers, json={
        "fact_key": "pro.monthly", "fact_type": "price", "entity_name": "ContexA Pro",
        "canonical_value": "INR 54,999/month", "source_document": "approved-price-book.txt",
        "source_quote": "ContexA Pro monthly subscription is INR 54,999, effective 1 October 2026.",
        "source_document_id": source.json()["id"]})
    assert good.status_code == 201, good.text
    assert good.json()["source_verified"] is True
    approved = client.post(f"/api/facts/{good.json()['id']}/approve", headers=headers)
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"


def test_asset_registry_approval_download_and_workspace_isolation(client: TestClient):
    from io import BytesIO
    from PIL import Image
    owner = register_workspace(client)
    other = register_workspace(client)
    output = BytesIO()
    Image.new("RGB", (32, 32), (210, 180, 120)).save(output, format="PNG")
    uploaded = client.post("/api/assets/upload?category=logo&name=Primary%20Logo", headers=owner,
        files={"file": ("primary.png", output.getvalue(), "image/png")})
    assert uploaded.status_code == 201, uploaded.text
    asset_id = uploaded.json()["id"]
    assert uploaded.json()["status"] == "draft"
    assert client.get("/api/assets", headers=other).json() == []
    approved = client.post(f"/api/assets/{asset_id}/approve", headers=owner)
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    download = client.get(f"/api/assets/{asset_id}/download", headers=owner)
    assert download.status_code == 200 and download.content.startswith(b"\x89PNG")
    assert client.get(f"/api/assets/{asset_id}/download", headers=other).status_code == 404


def test_upload_rejects_extension_signature_mismatch(client: TestClient):
    headers = register_workspace(client)
    response = client.post("/api/documents/upload", headers=headers,
        files={"file": ("pretend.pdf", b"this is not a pdf", "application/pdf")})
    assert response.status_code == 422
    assert "PDF signature" in response.json()["detail"]


def test_email_verification_password_reset_and_workspace_invitation(client: TestClient, monkeypatch):
    import urllib.parse
    import app.main as main_module
    monkeypatch.setattr(main_module, "EMAIL_VERIFICATION_REQUIRED", True)
    email = f"verify-{uuid.uuid4().hex[:10]}@example.test"
    registered = client.post("/api/auth/register", json={
        "name": "Verified Owner", "email": email, "password": "SafePassword-2026!",
        "workspace_name": "Verified Workspace"})
    assert registered.status_code == 201, registered.text
    assert registered.json()["verification_required"] is True
    link = registered.json()["debug_link"]
    token = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)["verify-email_token"][0]
    assert client.post("/api/auth/login", json={"email": email, "password": "SafePassword-2026!"}).status_code == 403
    verified = client.post("/api/auth/verify-email", json={"token": token})
    assert verified.status_code == 200 and verified.json()["verified"] is True
    login = client.post("/api/auth/login", json={"email": email, "password": "SafePassword-2026!"})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    forgot = client.post("/api/auth/password/forgot", json={"email": email})
    assert forgot.status_code == 200 and forgot.json().get("debug_link")
    reset_token = urllib.parse.parse_qs(urllib.parse.urlparse(forgot.json()["debug_link"]).query)["password-reset_token"][0]
    reset = client.post("/api/auth/password/reset", json={"token": reset_token, "password": "NewSafePassword-2026!"})
    assert reset.status_code == 200
    # Password reset revokes tokens issued before the reset. Re-authenticate before inviting.
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    refreshed_login = client.post("/api/auth/login", json={"email": email, "password": "NewSafePassword-2026!"})
    assert refreshed_login.status_code == 200
    headers = {"Authorization": f"Bearer {refreshed_login.json()['access_token']}"}

    invited_email = f"member-{uuid.uuid4().hex[:10]}@example.test"
    invitation = client.post("/api/invitations", headers=headers, json={"email": invited_email, "role": "Manager"})
    assert invitation.status_code == 201, invitation.text
    invite_token = urllib.parse.parse_qs(urllib.parse.urlparse(invitation.json()["debug_link"]).query)["workspace-invite_token"][0]
    accepted = client.post("/api/invitations/accept", json={"token": invite_token,
        "name": "Workspace Manager", "password": "MemberSafePassword-2026!"})
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["user"]["workspace_id"] == login.json()["user"]["workspace_id"]
    assert accepted.json()["user"]["role"] == "Manager"


def test_brand_intelligence_includes_asset_governance(client: TestClient):
    headers = register_workspace(client)
    result = client.get("/api/brand-intelligence", headers=headers)
    assert result.status_code == 200
    assert result.json()["assets"] == {"total": 0, "approved": 0, "draft": 0, "archived": 0, "categories": {}}


def test_guideline_import_indexes_page_aware_chunks_and_hybrid_search(client: TestClient):
    headers = register_workspace(client)
    guideline = ("PRICING AND PROMOTIONS\n"
        "All published prices must match the currently approved price book.\n"
        "Promotional discounts must include eligibility terms and the offer expiry date.\n"
        "Comparative performance claims require documented and current substantiation.\n" * 18)
    imported = client.post("/api/guidelines/import", headers=headers,
        files={"file": ("pricing-guidelines.txt", guideline.encode(), "text/plain")})
    assert imported.status_code == 200, imported.text
    assert imported.json()["created_rules"] > 0
    search = client.post("/api/retrieval/search", headers=headers,
        json={"query": "approved price book promotional discounts expiry"})
    assert search.status_code == 200, search.text
    assert search.json()["retrieval_mode"] == "offline-hybrid"
    assert search.json()["results"]
    first = search.json()["results"][0]
    assert first["source_document"] == "pricing-guidelines.txt"
    assert first["page_number"] >= 1
    assert first["source_sha256"]
    rebuilt = client.post("/api/admin/rebuild-embeddings", headers=headers)
    assert rebuilt.status_code == 200, rebuilt.text
    assert rebuilt.json()["chunks_rebuilt"] >= 1
    assert rebuilt.json()["embedding_model"] == "hashed-token-v1"


def test_login_rate_limit_persists_lockout(client: TestClient, monkeypatch):
    import app.main as main_module
    monkeypatch.setattr(main_module, "LOGIN_MAX_FAILURES", 2)
    email = f"lock-{uuid.uuid4().hex[:10]}@example.test"
    registered = client.post("/api/auth/register", json={
        "name": "Lock Test", "email": email, "password": "LockTest-StrongPassword-77"})
    assert registered.status_code == 201
    first = client.post("/api/auth/login", json={"email": email, "password": "Wrong-Password-1"})
    second = client.post("/api/auth/login", json={"email": email, "password": "Wrong-Password-2"})
    third = client.post("/api/auth/login", json={"email": email, "password": "LockTest-StrongPassword-77"})
    assert first.status_code == 401
    assert second.status_code == 401
    assert third.status_code == 429


def test_workspace_export_contains_manifest_and_source_files(client: TestClient):
    import io, json, zipfile
    headers = register_workspace(client)
    uploaded = client.post("/api/documents/upload", headers=headers, files={
        "file": ("brand-source.txt", b"Approved brand source text for export.", "text/plain")})
    assert uploaded.status_code == 201, uploaded.text
    exported = client.get("/api/workspace/export", headers=headers)
    assert exported.status_code == 200, exported.text
    assert exported.headers.get("content-type", "").startswith("application/zip")
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["collections"]["users"]
        assert "password_hash" not in json.dumps(manifest)
        assert any(name.endswith("brand-source.txt") for name in archive.namelist())


def test_workspace_deletion_requires_exact_confirmation_and_password(client: TestClient):
    headers = register_workspace(client)
    uploaded = client.post("/api/documents/upload", headers=headers, files={
        "file": ("private.txt", b"Private workspace content.", "text/plain")})
    assert uploaded.status_code == 201
    wrong_name = client.request("DELETE", "/api/workspace", headers=headers, json={
        "password": "RoundThree-Safe-Password-42", "workspace_name_confirmation": "Wrong Name"})
    assert wrong_name.status_code == 400
    wrong_password = client.request("DELETE", "/api/workspace", headers=headers, json={
        "password": "not-the-password", "workspace_name_confirmation": "Round Three Lab"})
    assert wrong_password.status_code == 403
    deleted = client.request("DELETE", "/api/workspace", headers=headers, json={
        "password": "RoundThree-Safe-Password-42", "workspace_name_confirmation": "Round Three Lab"})
    assert deleted.status_code == 204, deleted.text
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_passwords_use_argon2id_when_available():
    from app.security import hash_password, verify_password, password_needs_rehash
    encoded = hash_password("Strong-Test-Password-2026")
    assert encoded.startswith("$argon2id$") or encoded.startswith("pbkdf2_sha256$")
    assert verify_password("Strong-Test-Password-2026", encoded)
    assert not verify_password("incorrect-password", encoded)


def test_private_object_storage_local_roundtrip_and_path_guard(tmp_path, monkeypatch):
    import app.object_storage as storage
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path.resolve())
    monkeypatch.setattr(storage, "S3_BUCKET", "")
    key = storage.store_bytes(b"private-test-payload", "documents/nested/test.txt", "text/plain")
    assert storage.read_bytes(key) == b"private-test-payload"
    with pytest.raises(ValueError):
        storage.store_bytes(b"bad", "../../outside.txt", "text/plain")
    storage.delete_object(key)
    assert not (tmp_path / "documents/nested/test.txt").exists()


def test_audit_hash_chain_detects_modified_event(client: TestClient):
    from sqlalchemy import select, desc
    from app.database import SessionLocal
    from app.models import AuditEvent
    from app.security import decode_access_token
    headers = register_workspace(client)
    workspace_id = decode_access_token(headers["Authorization"].split(" ", 1)[1])["workspace_id"]
    uploaded = client.post("/api/documents/upload", headers=headers, files={
        "file": ("audit-chain.txt", b"This is our #1 fastest platform.", "text/plain")})
    assert uploaded.status_code == 201, uploaded.text
    first = client.get("/api/audit/verify", headers=headers)
    assert first.status_code == 200 and first.json()["valid"] is True
    with SessionLocal() as db:
        event = db.scalar(select(AuditEvent).where(AuditEvent.workspace_id == workspace_id).order_by(desc(AuditEvent.created_at), desc(AuditEvent.id)).limit(1))
        event.detail = {"tampered": True}
        db.commit()
    second = client.get("/api/audit/verify", headers=headers)
    assert second.status_code == 200 and second.json()["valid"] is False


def test_s3_compatible_storage_adapter_roundtrip(tmp_path, monkeypatch):
    import io
    import app.object_storage as storage
    class FakeS3:
        def __init__(self): self.objects = {}; self.deleted = []
        def put_object(self, **kwargs): self.objects[(kwargs["Bucket"], kwargs["Key"])] = kwargs["Body"]
        def get_object(self, **kwargs): return {"Body": io.BytesIO(self.objects[(kwargs["Bucket"], kwargs["Key"])])}
        def delete_object(self, **kwargs): self.deleted.append((kwargs["Bucket"], kwargs["Key"])); self.objects.pop((kwargs["Bucket"], kwargs["Key"]), None)
    fake = FakeS3()
    monkeypatch.setattr(storage, "S3_BUCKET", "test-private-bucket")
    monkeypatch.setattr(storage, "S3_PREFIX", "contexa-test")
    monkeypatch.setattr(storage, "_s3_client", lambda: fake)
    key = storage.store_bytes(b"s3-private-payload", "assets/logo.png", "image/png")
    assert key == "s3://test-private-bucket/contexa-test/assets/logo.png"
    assert storage.read_bytes(key) == b"s3-private-payload"
    storage.delete_object(key)
    assert fake.deleted == [("test-private-bucket", "contexa-test/assets/logo.png")]


def test_user_upload_rate_limit_is_enforced_per_account(client: TestClient, monkeypatch):
    import app.main as main_module
    headers = register_workspace(client)
    monkeypatch.setattr(main_module, "UPLOAD_MAX_PER_USER", 1)
    monkeypatch.setattr(main_module, "UPLOAD_WINDOW_MINUTES", 60)
    first = client.post("/api/documents/upload", headers=headers,
        files={"file": ("first.txt", b"A first harmless upload.", "text/plain")})
    assert first.status_code == 201, first.text
    second = client.post("/api/documents/upload", headers=headers,
        files={"file": ("second.txt", b"A second harmless upload.", "text/plain")})
    assert second.status_code == 429, second.text


def test_admin_can_deactivate_member_and_revoke_member_sessions(client: TestClient):
    admin_login = client.post("/api/auth/login", json={"email": "admin@contexa.local", "password": "ContexA!2026"})
    creator_login = client.post("/api/auth/login", json={"email": "creator@contexa.local", "password": "Creator!2026"})
    assert admin_login.status_code == creator_login.status_code == 200
    admin = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}
    creator = {"Authorization": f"Bearer {creator_login.json()['access_token']}"}
    creator_user = client.get("/api/auth/me", headers=creator).json()
    response = client.post(f"/api/users/{creator_user['id']}/deactivate", headers=admin)
    assert response.status_code == 200, response.text
    rejected = client.get("/api/auth/me", headers=creator)
    assert rejected.status_code == 401
    # Restore the seeded identity so this suite remains repeatable against a local
    # development database; the old token remains revoked by the version increment.
    from app.database import SessionLocal
    from app.models import User
    with SessionLocal() as db:
        member = db.query(User).filter(User.email == "creator@contexa.local").first()
        if member:
            member.is_active = True
            db.commit()


def test_postgres_rls_verifier_is_explicitly_not_applicable_to_sqlite():
    from app.database import verify_postgres_rls
    result = verify_postgres_rls()
    assert result == {"enabled": False, "reason": "not_postgresql"}


def test_human_labelled_evaluation_csv_import_and_workspace_validation(client: TestClient):
    headers = register_workspace(client)
    csv_payload = (
        "case_code,title,content_text,expected_rule_codes,category\n"
        'human-claim-01,Unsupported claim,"This is the #1 fastest platform.",CLM-204|LGL-002,claim\n'
        'human-clean-01,Clean control,"The team shared the approved launch calendar.",,control\n'
    ).encode("utf-8")
    imported = client.post("/api/evaluation/import", headers=headers,
        files={"file": ("human-labelled-cases.csv", csv_payload, "text/csv")})
    assert imported.status_code == 201, imported.text
    assert imported.json()["created"] == 2
    assert imported.json()["total"] >= 2
    run = client.post("/api/evaluation/run", headers=headers)
    assert run.status_code == 200, run.text
    assert run.json()["case_count"] >= 2

    invalid = client.post("/api/evaluation/import", headers=headers,
        files={"file": ("unknown-rule.csv", b"case_code,title,content_text,expected_rule_codes,category\nx1,Bad,Content,NOT-A-RULE,claim\n", "text/csv")})
    assert invalid.status_code == 422
