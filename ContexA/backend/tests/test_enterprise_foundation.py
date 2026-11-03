from __future__ import annotations

import hashlib
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def foundation_client():
    import app.main as main_module
    from app.database import SessionLocal
    from app.models import LoginAttempt

    main_module.SIGNUP_MAX_PER_IP = 1000
    signup_key = hashlib.sha256(b"signup|testclient").hexdigest()
    with TestClient(app) as client:
        with SessionLocal() as db:
            db.query(LoginAttempt).filter(LoginAttempt.identity_hash == signup_key).delete(synchronize_session=False)
            db.commit()
        yield client


def create_workspace(client: TestClient) -> dict[str, str]:
    email = f"foundation-{uuid.uuid4().hex[:12]}@example.test"
    response = client.post("/api/auth/register", json={
        "name": "Foundation Admin", "email": email,
        "password": "Foundation-Strong-Password-2026", "workspace_name": "Foundation Lab"})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def upload_text(client: TestClient, headers: dict[str, str]):
    response = client.post("/api/documents/upload", headers=headers, files={
        "file": ("graph-source.txt", b"The product has a two-year warranty. Verify against the official source.", "text/plain")})
    assert response.status_code == 201, response.text
    return response.json()


def test_foundation_status_reports_configured_and_development_boundaries(foundation_client):
    headers = create_workspace(foundation_client)
    response = foundation_client.get("/api/foundation/status", headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["identity"]["provider"] == "contexa_local"
    assert payload["trust_graph"]["enabled"] is True
    assert payload["decision_replay"]["replay_type"] == "integrity_replay_not_model_reexecution"
    assert payload["signing"]["provider"] in {"local_hmac", "aws_kms"}


def test_trust_graph_rebuild_indexes_real_workspace_records_and_isolates_tenants(foundation_client):
    first = create_workspace(foundation_client)
    second = create_workspace(foundation_client)
    doc = upload_text(foundation_client, first)
    agent = foundation_client.post("/api/agents/runs", headers=first, json={
        "objective": "Review graph document", "document_id": doc["id"]})
    assert agent.status_code == 201, agent.text
    rebuilt = foundation_client.post("/api/foundation/graph/rebuild", headers=first)
    assert rebuilt.status_code == 200, rebuilt.text
    assert rebuilt.json()["counts"]["documents"] >= 1
    assert rebuilt.json()["counts"]["agent_runs"] >= 1
    graph = foundation_client.get("/api/foundation/graph", headers=first)
    assert graph.status_code == 200
    assert any(n["external_id"] == doc["id"] and n["node_type"] == "document" for n in graph.json()["nodes"])
    other_graph = foundation_client.get("/api/foundation/graph", headers=second)
    assert other_graph.status_code == 200 and other_graph.json()["nodes"] == []


def test_agent_run_creates_replayable_integrity_trace(foundation_client):
    headers = create_workspace(foundation_client)
    run = foundation_client.post("/api/agents/runs", headers=headers, json={
        "objective": "Check an evidence-backed performance claim",
        "content_text": "Battery capacity is 5000 mAh. Warranty lasts 2 years."})
    assert run.status_code == 201, run.text
    traces = foundation_client.get("/api/foundation/decision-traces", headers=headers)
    assert traces.status_code == 200 and len(traces.json()) == 1
    trace = traces.json()[0]
    assert trace["agent_run_id"] == run.json()["id"]
    replay = foundation_client.get(f"/api/foundation/decision-traces/{trace['id']}/replay", headers=headers)
    assert replay.status_code == 200, replay.text
    assert replay.json()["integrity_valid"] is True
    assert replay.json()["input_hash_valid"] is True
    assert replay.json()["output_hash_valid"] is True
    assert "does not re-execute" in replay.json()["note"]


def test_admin_can_create_signed_merkle_anchor(foundation_client):
    headers = create_workspace(foundation_client)
    run = foundation_client.post("/api/agents/runs", headers=headers, json={
        "objective": "Produce audit events", "content_text": "This is a test claim."})
    assert run.status_code == 201
    created = foundation_client.post("/api/foundation/audit/anchors", headers=headers)
    assert created.status_code == 201, created.text
    anchor = created.json()
    assert len(anchor["root_sha256"]) == 64
    assert anchor["leaf_count"] >= 1
    listed = foundation_client.get("/api/foundation/audit/anchors", headers=headers)
    assert listed.status_code == 200 and listed.json()[0]["root_sha256"] == anchor["root_sha256"]
    verified = foundation_client.get(f"/api/foundation/audit/anchors/{anchor['id']}/verify", headers=headers)
    assert verified.status_code == 200 and verified.json()["signature_valid"] is True


def test_local_signer_detects_manifest_tampering():
    from app.cloud_providers import sign_manifest, verify_manifest

    manifest = {"schema": "test/1", "asset_sha256": "a" * 64, "issued_at": "2026-11-01T00:00:00Z"}
    signature = sign_manifest(manifest)
    assert verify_manifest(manifest, signature) is True
    changed = {**manifest, "asset_sha256": "b" * 64}
    assert verify_manifest(changed, signature) is False


def test_local_archive_is_explicitly_not_immutable(tmp_path, monkeypatch):
    import app.cloud_providers as providers

    monkeypatch.setattr(providers, "EVIDENCE_ARCHIVE_BUCKET", "")
    monkeypatch.setattr(providers, "STORAGE_DIR", tmp_path)
    data = b'{"record":"signed manifest"}'
    archive = providers.archive_evidence(data, "passports/public-id/manifest.json")
    assert archive["provider"] == "local_filesystem"
    assert archive["immutable"] is False
    assert Path(archive["uri"]).read_bytes() == data
    # Deterministic key reuse with different bytes must fail rather than overwrite evidence.
    with pytest.raises(RuntimeError, match="different content"):
        providers.archive_evidence(b"tampered", "passports/public-id/manifest.json")


def test_supabase_jwt_verification_checks_signature_issuer_audience_and_verified_email(monkeypatch):
    import app.security as security
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    monkeypatch.setattr(security, "SUPABASE_JWKS_URL", "https://example.supabase.co/auth/v1/.well-known/jwks.json")
    monkeypatch.setattr(security, "SUPABASE_JWT_ISSUER", "https://example.supabase.co/auth/v1")
    monkeypatch.setattr(security, "SUPABASE_JWT_AUDIENCE", "authenticated")
    monkeypatch.setattr(security, "SUPABASE_JWT_ALGORITHMS", ["RS256"])
    monkeypatch.setattr(security, "SUPABASE_REQUIRE_AAL2", False)
    monkeypatch.setattr(security, "_SUPABASE_JWKS_CLIENT", SimpleNamespace(
        get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=public_key)))
    issued_at = int(time.time())
    claims = {"sub": str(uuid.uuid4()), "email": "verified@example.test", "email_verified": True,
        "iss": "https://example.supabase.co/auth/v1", "aud": "authenticated", "iat": issued_at,
        "exp": issued_at + 3600, "aal": "aal1"}
    token = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "test-key"})
    assert security.decode_supabase_access_token(token)["sub"] == claims["sub"]
    bad_claims = {**claims, "email_verified": False}
    bad_token = jwt.encode(bad_claims, private_key, algorithm="RS256", headers={"kid": "test-key"})
    with pytest.raises(Exception, match="Invalid Supabase session"):
        security.decode_supabase_access_token(bad_token)


def test_verified_supabase_identity_links_only_to_matching_existing_account(foundation_client, monkeypatch):
    import app.security as security
    from app.database import SessionLocal
    from app.models import User
    from sqlalchemy import select

    headers = create_workspace(foundation_client)
    me = foundation_client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    subject = f"supabase-{uuid.uuid4()}"
    monkeypatch.setattr(security, "AUTH_MODE", "hybrid")
    monkeypatch.setattr(security, "decode_supabase_access_token", lambda _token: {
        "sub": subject, "email": me.json()["email"], "email_verified": True})
    with SessionLocal() as db:
        user = security.get_current_user(
            credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials="header.payload.signature"), db=db)
        assert user.email == me.json()["email"]
        assert user.supabase_subject == subject
        assert user.is_email_verified is True


def test_aws_kms_style_passport_signature_is_verifiable_offline_from_public_key():
    import base64
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa, utils
    from app.cloud_providers import canonical_json, verify_manifest

    manifest = {"schema": "contexa-passport/1", "passport_id": "public-test", "asset_sha256": "c" * 64}
    body = canonical_json(manifest)
    digest = hashlib.sha256(body).digest()
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    signature = private_key.sign(digest,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256().digest_size),
        utils.Prehashed(hashes.SHA256()))
    public_der = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo)
    fields = {
        "provider": "aws_kms", "key_id": "arn:aws:kms:ap-south-1:123456789012:key/test",
        "algorithm": "RSASSA_PSS_SHA_256",
        "signature_b64": base64.b64encode(signature).decode("ascii"),
        "public_key_b64": base64.b64encode(public_der).decode("ascii"),
        "manifest_sha256": hashlib.sha256(body).hexdigest(),
    }
    assert verify_manifest(manifest, fields) is True
    assert verify_manifest({**manifest, "asset_sha256": "d" * 64}, fields) is False


def test_s3_archive_only_reports_immutable_after_retention_readback(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    import app.cloud_providers as providers

    class FakeS3:
        def __init__(self, mode="GOVERNANCE", missing=False):
            self.mode = mode
            self.missing = missing
            self.put_args = None
        def put_object(self, **kwargs):
            self.put_args = kwargs
            return {"VersionId": "version-verified-001"}
        def get_object_retention(self, **kwargs):
            assert kwargs["VersionId"] == "version-verified-001"
            if self.missing:
                return {"Retention": {"Mode": "GOVERNANCE", "RetainUntilDate": datetime.now(timezone.utc)}}
            return {"Retention": {"Mode": self.mode, "RetainUntilDate": self.put_args["ObjectLockRetainUntilDate"] + timedelta(days=1)}}

    fake = FakeS3()
    monkeypatch.setattr(providers, "EVIDENCE_ARCHIVE_BUCKET", "contexa-evidence-test")
    monkeypatch.setattr(providers, "EVIDENCE_ARCHIVE_PREFIX", "contexa")
    monkeypatch.setattr(providers, "EVIDENCE_ARCHIVE_RETENTION_DAYS", 30)
    monkeypatch.setattr(providers, "EVIDENCE_ARCHIVE_MODE", "GOVERNANCE")
    monkeypatch.setattr(providers, "EVIDENCE_ARCHIVE_SSE", "aws:kms")
    monkeypatch.setattr(providers, "EVIDENCE_ARCHIVE_KMS_KEY_ID", "arn:aws:kms:test:key/evidence")
    monkeypatch.setattr(providers, "_aws_client", lambda _service: fake)
    result = providers.archive_evidence(b"signed-manifest", "passports/test/manifest.json")
    assert result["immutable"] is True
    assert result["version_id"] == "version-verified-001"
    assert result["object_lock_mode"] == "GOVERNANCE"
    assert result["sha256"] == hashlib.sha256(b"signed-manifest").hexdigest()

    fake_missing = FakeS3(missing=True)
    monkeypatch.setattr(providers, "_aws_client", lambda _service: fake_missing)
    with pytest.raises(RuntimeError, match="read-back"):
        providers.archive_evidence(b"signed-manifest-2", "passports/test/manifest-2.json")


def test_supabase_session_check_blocks_missing_database_url(monkeypatch):
    import app.security as security
    from fastapi import HTTPException

    monkeypatch.setattr(security, "SUPABASE_SESSION_CHECK_REQUIRED", True)
    monkeypatch.setattr(security, "SUPABASE_SESSION_DATABASE_URL", "")
    with pytest.raises(HTTPException) as error:
        security._require_active_supabase_session({
            "session_id": str(uuid.uuid4()), "sub": str(uuid.uuid4())})
    assert error.value.status_code == 503
    assert "SUPABASE_SESSION_DATABASE_URL" in error.value.detail


def test_supabase_session_check_rejects_missing_or_revoked_session(monkeypatch):
    import app.security as security
    from fastapi import HTTPException

    class FakeConnection:
        def __init__(self, value):
            self.value = value
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def scalar(self, *_args, **_kwargs):
            return self.value

    class FakeEngine:
        def __init__(self, value):
            self.value = value
        def connect(self):
            return FakeConnection(self.value)

    sid, uid = str(uuid.uuid4()), str(uuid.uuid4())
    monkeypatch.setattr(security, "SUPABASE_SESSION_CHECK_REQUIRED", True)
    monkeypatch.setattr(security, "SUPABASE_SESSION_DATABASE_URL", "postgresql+psycopg://test")
    monkeypatch.setattr(security, "_SUPABASE_SESSION_ENGINE", FakeEngine(None))
    with pytest.raises(HTTPException) as error:
        security._require_active_supabase_session({"session_id": sid, "sub": uid})
    assert error.value.status_code == 401
    assert "revoked" in error.value.detail

    monkeypatch.setattr(security, "_SUPABASE_SESSION_ENGINE", FakeEngine(1))
    security._require_active_supabase_session({"session_id": sid, "sub": uid})


def test_supabase_session_check_fails_closed_on_database_outage(monkeypatch):
    import app.security as security
    from fastapi import HTTPException

    class BrokenEngine:
        def connect(self):
            raise OSError("simulated auth database outage")

    monkeypatch.setattr(security, "SUPABASE_SESSION_CHECK_REQUIRED", True)
    monkeypatch.setattr(security, "SUPABASE_SESSION_DATABASE_URL", "postgresql+psycopg://test")
    monkeypatch.setattr(security, "_SUPABASE_SESSION_ENGINE", BrokenEngine())
    with pytest.raises(HTTPException) as error:
        security._require_active_supabase_session({
            "session_id": str(uuid.uuid4()), "sub": str(uuid.uuid4())})
    assert error.value.status_code == 503
    assert "temporarily blocked" in error.value.detail


def test_supabase_revoke_calls_local_auth_logout_endpoint(monkeypatch):
    import app.security as security
    from urllib.parse import urlsplit, parse_qs

    captured = {}

    class FakeResponse:
        status = 204
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = {key.lower(): value for key, value in request.header_items()}
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(security, "SUPABASE_URL", "https://tenant.example.supabase.co")
    monkeypatch.setattr(security, "SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test-public-key")
    monkeypatch.setattr(security, "urlopen", fake_urlopen)
    security.revoke_supabase_session("header.payload.signature")

    assert urlsplit(captured["url"]).path == "/auth/v1/logout"
    assert parse_qs(urlsplit(captured["url"]).query) == {"scope": ["local"]}
    assert captured["headers"]["apikey"] == "sb_publishable_test-public-key"
    assert captured["headers"]["authorization"] == "Bearer header.payload.signature"
    assert captured["timeout"] == 12


def test_supabase_logout_route_revokes_only_provider_session(foundation_client, monkeypatch):
    import app.main as main_module
    import app.security as security
    from app.database import SessionLocal
    from app.models import User
    from sqlalchemy import select

    headers = create_workspace(foundation_client)
    profile = foundation_client.get("/api/auth/me", headers=headers).json()
    original_version = None
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.id == profile["id"]))
        original_version = user.token_version

    subject = str(uuid.uuid4())
    monkeypatch.setattr(main_module, "AUTH_MODE", "hybrid")
    monkeypatch.setattr(security, "AUTH_MODE", "hybrid")
    monkeypatch.setattr(security, "decode_supabase_access_token", lambda _token: {
        "sub": subject, "email": profile["email"], "email_verified": True})
    calls = []
    monkeypatch.setattr(main_module, "revoke_supabase_session", lambda token: calls.append(token))

    response = foundation_client.post("/api/auth/logout", headers={
        "Authorization": "Bearer header.payload.signature"})
    assert response.status_code == 200, response.text
    assert calls == ["header.payload.signature"]
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.id == profile["id"]))
        assert user.token_version == original_version
