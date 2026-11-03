from __future__ import annotations

import csv
import io
import json
import hashlib
import time
import zipfile
import logging
import os
import re
import uuid
import secrets
import smtplib
import hashlib
from urllib.request import Request as URLRequest, urlopen
from urllib.error import URLError, HTTPError
from email.message import EmailMessage
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import fitz
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc, func, inspect as sqlalchemy_inspect, select, text
from sqlalchemy.orm import Session, joinedload

from .config import (
    APP_ENV, APP_NAME, MAX_UPLOAD_MB, STORAGE_DIR, WORKSPACE_ID, ENABLE_POSTGRES_RLS, ALLOW_SIGNUP, SECRET_KEY,
    STORE_UPLOADS_IN_DATABASE, ANTHROPIC_API_KEY, ANTHROPIC_MODEL, DATABASE_URL, OLLAMA_MODEL, AI_VERIFICATION_ENABLED,
    EMAIL_VERIFICATION_REQUIRED, SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_EMAIL, SMTP_FROM_NAME,
    SMTP_USE_TLS, SMTP_USE_SSL, PUBLIC_APP_URL, AUTH_TOKEN_MINUTES, LOGIN_MAX_FAILURES, LOGIN_LOCK_MINUTES,
    UPLOAD_SCAN_MODE, OLLAMA_EMBEDDINGS_ENABLED, OLLAMA_EMBEDDING_MODEL, SIGNUP_MAX_PER_IP, SIGNUP_WINDOW_MINUTES,
    PASSWORD_RESET_MAX_PER_IP, UPLOAD_MAX_PER_USER, UPLOAD_WINDOW_MINUTES, AUTH_TOKEN_RETENTION_DAYS,
    LOGIN_ATTEMPT_RETENTION_DAYS, S3_BUCKET, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, REQUIRE_PRIVATE_OBJECT_STORAGE,
    REQUIRE_MALWARE_SCAN, SECURITY_HEADERS_ENABLED, TURNSTILE_SECRET_KEY, TURNSTILE_EXPECTED_HOSTNAME,
    CLOUDFLARE_EDGE_ENABLED, CLOUDFLARE_ORIGIN_SHARED_SECRET, PUBLIC_API_URL, ANTHROPIC_BASE_URL,
    CLOUDFLARE_AI_GATEWAY_TOKEN, TRUST_PASSPORT_SIGNING_KEY, TRUTH_DRIFT_CRON_TOKEN, TRUST_SIGNING_PROVIDER,
    TRUST_KMS_KEY_ID, EVIDENCE_ARCHIVE_BUCKET, EVIDENCE_ARCHIVE_RETENTION_DAYS, EVIDENCE_ARCHIVE_MODE,
    TRUST_ARCHIVE_REQUIRED, AUTH_MODE, SUPABASE_URL, SUPABASE_JWT_ISSUER, SUPABASE_JWKS_URL,
    SUPABASE_JWT_ALGORITHMS, SUPABASE_REQUIRE_AAL2, CSP_EXTRA_CONNECT_ORIGINS,
    SUPABASE_SESSION_DATABASE_URL, SUPABASE_SESSION_CHECK_REQUIRED, SUPABASE_PUBLISHABLE_KEY,
)
from .database import Base, SessionLocal, engine, get_db, prepare_database, set_workspace_context, enable_postgres_rls
from .migrations import run_migrations
from .collaboration import router as collaboration_router, install_observability, notify, record_snapshot, workspace_admin_ids
from .embeddings import embed, embed_with_model, hybrid_score, embedding_model_label
from .inspection import inspect_content, local_ai_status
from .models import (AuditEvent, BrandRule, ContentDocument, ReviewFinding, User, utcnow, RuleVersion, ApprovedFact, ScanRun, FindingEvidence, PolicySimulation, EvaluationCase, EvaluationRun, ReviewTask, BrandAsset, AuthActionToken, LoginAttempt, GuidelineChunk, MonitoredSource, TruthDriftEvent, TrustPassport, MediaInspection, AgentRun, DigitalTwinScenario, LanguageReview, RegulatoryRequirement, RegulatoryAssessment, BrandIncident, PublicPassportIndex)
from .parsing import ALLOWED_EXTENSIONS, parse_document
from .schemas import (DashboardOut, DocumentOut, FindingAction, FindingActionResponse, FindingOut,
                      InsightOut, InsightRule, LoginRequest, LoginResponse, RegisterRequest, PublishRequest,
                      RuleCreate, RuleOut, RuleUpdate, UserOut, CopyCheckRequest, FactCreate, FactRevision, PolicySimulationRequest, PolicyApplyRequest, ReviewTaskUpdate, TokenRequest, PasswordResetRequest, InvitationCreate, InvitationAccept, WorkspaceDeleteRequest)
from .security import bearer, create_access_token, get_current_user, hash_password, password_needs_rehash, require_roles, verify_password, revoke_supabase_session
from .upload_security import read_upload_limited, validate_upload_payload, clamav_scan, sha256_hex
from .object_storage import store_bytes, read_bytes as read_stored_bytes, delete_object as delete_stored_object

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("contexa")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Run the existing production checks and initialization through FastAPI lifespan."""
    startup()
    yield


app = FastAPI(title=APP_NAME, version="1.0.0", description="Pre-publication brand-governance and audit platform", lifespan=lifespan)
_default_origins = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173"
_allowed_origins = [origin.strip().rstrip("/") for origin in os.getenv("ALLOWED_ORIGINS", _default_origins).split(",") if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_allowed_origins,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Request-ID"])
install_observability(app)
app.include_router(collaboration_router)


def _origin_only(value: str) -> str | None:
    """Return a safe HTTP(S) origin for CSP; paths, credentials and fragments are rejected."""
    try:
        parsed = urlsplit((value or "").strip())
        if (parsed.scheme not in {"https", "http"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment):
            return None
        host = parsed.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://{host}{port}"
    except ValueError:
        return None


def _validate_production_cors_origins() -> None:
    """Require explicit HTTPS browser origins in production; never fall back to localhost."""
    configured = os.getenv("ALLOWED_ORIGINS", "").strip()
    if not configured:
        raise RuntimeError("Production requires ALLOWED_ORIGINS with one or more exact HTTPS frontend origins.")
    origins = [value.strip().rstrip("/") for value in configured.split(",") if value.strip()]
    if not origins:
        raise RuntimeError("Production ALLOWED_ORIGINS must contain at least one origin.")
    for origin in origins:
        parsed = urlsplit(origin)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
                or parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}):
            raise RuntimeError("Production ALLOWED_ORIGINS must contain exact HTTPS origins only (no paths, wildcards or localhost).")


def _csp_connect_sources() -> str:
    """Build connect-src from configured provider/API origins, not a hard-coded project."""
    origins = ["'self'", "https://challenges.cloudflare.com"]
    for candidate in (SUPABASE_URL, PUBLIC_API_URL):
        origin = _origin_only(candidate)
        if origin:
            origins.append(origin)
    if APP_ENV.lower() != "production":
        origins.extend(["http://localhost:8000", "http://127.0.0.1:8000"])
    for candidate in CSP_EXTRA_CONNECT_ORIGINS.split(","):
        origin = _origin_only(candidate)
        if origin:
            origins.append(origin)
    return " ".join(dict.fromkeys(origins))


@app.middleware("http")
async def security_headers_and_request_id(request: Request, call_next):
    """Protect the API origin and set baseline browser security headers/request IDs."""
    if (CLOUDFLARE_EDGE_ENABLED and CLOUDFLARE_ORIGIN_SHARED_SECRET
            and request.url.path.startswith("/api/")):
        supplied_origin_secret = request.headers.get("x-contexa-origin-secret", "")
        if not secrets.compare_digest(supplied_origin_secret, CLOUDFLARE_ORIGIN_SHARED_SECRET):
            response = Response(
                content=json.dumps({"detail": "API requests must pass through the configured edge gateway."}),
                status_code=403, media_type="application/json",
            )
        else:
            response = await call_next(request)
    else:
        response = await call_next(request)
    supplied = request.headers.get("x-request-id", "")
    request_id = supplied[:80] if re.fullmatch(r"[A-Za-z0-9._-]{8,80}", supplied) else str(uuid.uuid4())
    response.headers["X-Request-ID"] = request_id
    if SECURITY_HEADERS_ENABLED:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; "
            "script-src 'self' https://challenges.cloudflare.com; frame-src https://challenges.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data: blob:; "
            f"connect-src {_csp_connect_sources()}; upgrade-insecure-requests"
        )
        if APP_ENV.lower() == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith("/api/auth/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response

ROLES = ["Creator", "Manager", "SME / Legal", "Brand Admin"]

SEED_RULES = [
    {"code": "CLM-204", "title": "Substantiate absolute and quantified claims", "category": "claim", "severity": "critical",
     "rule_clause": "Claims about rankings, guarantees, performance, revenue, or quantified outcomes require documented substantiation and appropriate legal review before publication.",
     "source_document": "Legal Claims Standard v3", "pattern": r"#\s?1\b|number\s+one|\b(?:fastest|best|guaranteed|unmatched|unparalleled|never fails)\b|\b(?:increase|boost|grow|reduce|save|improve|cut|deliver)[^.!?\n]{0,55}\b\d{1,3}(?:\.\d+)?\s?%",
     "suggested_fix": "Replace the absolute claim with a specific, evidenced statement. Link the supporting study or approved proof point and send quantified claims to Legal."},
    {"code": "LGL-002", "title": "Add required disclaimer to promotional claims", "category": "legal", "severity": "critical",
     "rule_clause": "Absolute and quantified promotional statements must include the applicable legal disclaimer or an approved terms reference.",
     "source_document": "Legal Claims Standard v3", "pattern": None,
     "suggested_fix": "Add the approved disclaimer for this claim and confirm that the substantiation, scope, and limitations match the referenced evidence."},
    {"code": "TERM-001", "title": "Avoid unapproved superlatives", "category": "terminology", "severity": "warning",
     "rule_clause": "Avoid unsupported or unapproved superlatives such as revolutionary, world-class, unmatched, and unparalleled unless specifically approved by Brand and Legal.",
     "source_document": "Brand Voice Guidelines v2.1", "pattern": r"\b(?:revolutionary|world[- ]class|unmatched|unparalleled|game[- ]changing)\b",
     "suggested_fix": "Replace the superlative with a concrete product capability or a substantiated, measurable benefit."},
    {"code": "TONE-003", "title": "Use evidence-led, respectful language", "category": "tone", "severity": "warning",
     "rule_clause": "Brand communications should be precise and respectful. Avoid dismissive or absolute phrases that pressure readers without evidence.",
     "source_document": "Brand Voice Guidelines v2.1", "pattern": r"\b(?:obviously|everyone knows|simply the best|no-brainer|idiot[- ]proof)\b",
     "suggested_fix": "Rewrite in direct, neutral language and explain the supporting reason or evidence."},
    {"code": "TERM-008", "title": "Use the approved product name", "category": "terminology", "severity": "warning",
     "rule_clause": "The product name in customer-facing copy must be written as ContexA, with an uppercase A, and must not be shortened to Context A or Contexa.",
     "source_document": "Brand Identity Standards v1.4", "pattern": r"(?-i:\bContexa\b)|\bContext\s+A\b",
     "suggested_fix": "Use the approved product spelling: ContexA."},
    {"code": "VIS-001", "title": "Meet WCAG text contrast", "category": "contrast", "severity": "warning",
     "rule_clause": "Normal text should meet a WCAG 2.1 contrast ratio of at least 4.5:1 and large text at least 3:1. Automated checks assume a white background; visually verify text placed on imagery or colored fills.",
     "source_document": "Digital Accessibility Standard WCAG 2.1", "pattern": None,
     "suggested_fix": "Increase foreground/background contrast, use a compliant brand color, or adjust font size and weight. Verify against the actual background."},
    {"code": "ASSET-005", "title": "Preserve approved asset clearspace", "category": "asset", "severity": "info",
     "rule_clause": "Approved logos and core identity assets must retain their documented clearspace and must not be stretched or cropped.",
     "source_document": "Brand Identity Standards v1.4", "pattern": None,
     "suggested_fix": "Compare the asset placement with the approved brand asset and restore the required clearspace. This text check cannot verify the full visual rule."},
    {"code": "PRC-002", "title": "Verify prices and promotions against the current source", "category": "pricing", "severity": "warning",
     "rule_clause": "Any published price, discount, savings figure, or promotional validity period must match the currently approved price book and campaign terms. A number alone does not establish whether a price is current.",
     "source_document": "Pricing & Promotions Control Standard v1.0", "pattern": r"(?:[$€£₹]\s?\d[\d,]*(?:\.\d{1,2})?|\b\d{1,2}%\s?(?:off|discount|saving|savings|less)\b|\b(?:starting at|only|price|pricing|promo code|offer ends|valid until)\b)",
     "suggested_fix": "Confirm the exact amount, currency, eligibility and end date against the current approved price book or campaign brief. This detector flags pricing references; it cannot determine freshness without a connected source of truth."},
    {"code": "A11Y-001", "title": "Provide meaningful image alternative text", "category": "accessibility", "severity": "warning",
     "rule_clause": "Meaningful images need concise alternative text that conveys their purpose. Decorative images should be marked decorative. Do not repeat surrounding text verbatim.",
     "source_document": "Digital Accessibility Standard WCAG 2.1", "pattern": None,
     "suggested_fix": "Add concise descriptive alt text to the image properties. For decorative imagery, mark it decorative. For PowerPoint, add the description through the image Alt Text panel."},
]


def _audit_hash(event: AuditEvent, previous_hash: str) -> str:
    created_at = event.created_at
    if created_at is not None and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    payload = {"id": event.id, "workspace_id": event.workspace_id, "actor_id": event.actor_id,
        "actor_name": event.actor_name, "action": event.action, "entity_type": event.entity_type,
        "entity_id": event.entity_id, "detail": event.detail or {},
        "created_at": created_at.isoformat() if created_at else None, "previous_hash": previous_hash}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _audit(db: Session, user: User, action: str, entity_type: str, entity_id: str,
           detail: dict[str, Any] | None = None) -> AuditEvent:
    # Serialize audit-head updates across concurrent PostgreSQL requests per workspace.
    if engine.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:workspace_id))"), {"workspace_id": user.workspace_id})
    previous = db.scalar(select(AuditEvent).where(AuditEvent.workspace_id == user.workspace_id)
        .order_by(desc(AuditEvent.created_at), desc(AuditEvent.id)).limit(1))
    previous_hash = (previous.event_hash if previous and previous.event_hash else
        _audit_hash(previous, "0" * 64) if previous else "0" * 64)
    event = AuditEvent(id=str(uuid.uuid4()), workspace_id=user.workspace_id, actor_id=user.id,
        actor_name=user.name, action=action, entity_type=entity_type, entity_id=entity_id,
        detail=detail or {}, previous_hash=previous_hash, created_at=utcnow())
    event.event_hash = _audit_hash(event, previous_hash)
    db.add(event)
    return event


def _ensure_user_workspace_columns() -> None:
    """Small forward-compatible migration for existing SQLite/PostgreSQL databases."""
    try:
        columns = {c["name"] for c in sqlalchemy_inspect(engine).get_columns("users")}
        with engine.begin() as conn:
            if "workspace_id" not in columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN workspace_id VARCHAR(80) NOT NULL DEFAULT 'ws-contexa-demo'"))
            if "workspace_name" not in columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN workspace_name VARCHAR(140) NOT NULL DEFAULT 'ContexA Demo Workspace'"))
            doc_columns = {c["name"] for c in sqlalchemy_inspect(engine).get_columns("content_documents")}
            if "file_data" not in doc_columns:
                binary_type = str(__import__("sqlalchemy").LargeBinary().compile(dialect=engine.dialect))
                conn.execute(text(f"ALTER TABLE content_documents ADD COLUMN file_data {binary_type}"))
            # Older versions used a single configured demo workspace. Keep its legacy members together.
            conn.execute(text("UPDATE users SET workspace_id = :wid WHERE workspace_id IS NULL OR workspace_id = ''"), {"wid": WORKSPACE_ID})
            conn.execute(text("UPDATE users SET workspace_name = 'ContexA Demo Workspace' WHERE workspace_name IS NULL OR workspace_name = ''"))
    except Exception:
        logger.exception("User workspace migration failed")
        raise


def _ensure_round3_columns() -> None:
    """Small additive migration for databases created by earlier ContexA releases."""
    finding_columns = {c["name"] for c in sqlalchemy_inspect(engine).get_columns("review_findings")}
    with engine.begin() as conn:
        if "rule_version_id" not in finding_columns:
            conn.execute(text("ALTER TABLE review_findings ADD COLUMN rule_version_id VARCHAR(36)"))
        doc_columns = {c["name"] for c in sqlalchemy_inspect(engine).get_columns("content_documents")}
        if "sha256" not in doc_columns:
            conn.execute(text("ALTER TABLE content_documents ADD COLUMN sha256 VARCHAR(64) NOT NULL DEFAULT ''"))
        if "scan_status" not in doc_columns:
            conn.execute(text("ALTER TABLE content_documents ADD COLUMN scan_status VARCHAR(24) NOT NULL DEFAULT 'not_configured'"))
        rule_columns = {c["name"] for c in sqlalchemy_inspect(engine).get_columns("brand_rules")}
        if "embedding_model" not in rule_columns:
            conn.execute(text("ALTER TABLE brand_rules ADD COLUMN embedding_model VARCHAR(100) NOT NULL DEFAULT 'hashed-token-v1'"))
        user_columns = {c["name"] for c in sqlalchemy_inspect(engine).get_columns("users")}
        if "is_email_verified" not in user_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN is_email_verified BOOLEAN NOT NULL DEFAULT TRUE"))
        if "email_verified_at" not in user_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN email_verified_at TIMESTAMP WITH TIME ZONE"))
        if "token_version" not in user_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0"))
        audit_columns = {c["name"] for c in sqlalchemy_inspect(engine).get_columns("audit_events")}
        if "previous_hash" not in audit_columns:
            conn.execute(text("ALTER TABLE audit_events ADD COLUMN previous_hash VARCHAR(64) NOT NULL DEFAULT ''"))
        if "event_hash" not in audit_columns:
            conn.execute(text("ALTER TABLE audit_events ADD COLUMN event_hash VARCHAR(64) NOT NULL DEFAULT ''"))
        if sqlalchemy_inspect(engine).has_table("approved_facts"):
            fact_columns = {c["name"] for c in sqlalchemy_inspect(engine).get_columns("approved_facts")}
            if "source_verified" not in fact_columns:
                conn.execute(text("ALTER TABLE approved_facts ADD COLUMN source_verified BOOLEAN NOT NULL DEFAULT FALSE"))


def _rule_snapshot(rule: BrandRule) -> dict[str, Any]:
    return {"code": rule.code, "title": rule.title, "category": rule.category,
            "rule_clause": rule.rule_clause, "source_document": rule.source_document,
            "pattern": rule.pattern, "severity": rule.severity,
            "suggested_fix": rule.suggested_fix, "is_active": rule.is_active}


def _record_rule_version(db: Session, rule: BrandRule, actor_id: str | None, note: str) -> RuleVersion:
    current = db.scalar(select(func.max(RuleVersion.version_number)).where(RuleVersion.rule_id == rule.id)) or 0
    version = RuleVersion(workspace_id=rule.workspace_id, rule_id=rule.id,
        version_number=current + 1, snapshot=_rule_snapshot(rule), change_note=note[:1000], created_by=actor_id)
    db.add(version)
    db.flush()
    return version


def _latest_rule_version(db: Session, rule: BrandRule | None) -> RuleVersion | None:
    if not rule:
        return None
    return db.scalar(select(RuleVersion).where(RuleVersion.rule_id == rule.id)
        .order_by(RuleVersion.version_number.desc()).limit(1))


def _ensure_rule_versions(db: Session, workspace_id: str) -> None:
    db.flush()
    rules = db.scalars(select(BrandRule).where(BrandRule.workspace_id == workspace_id)).all()
    for rule in rules:
        if not db.scalar(select(RuleVersion.id).where(RuleVersion.rule_id == rule.id).limit(1)):
            _record_rule_version(db, rule, None, "Initial snapshot migrated from an earlier ContexA release.")


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _numeric_amount(value: str) -> str | None:
    matches = re.findall(r"\d[\d,]*(?:\.\d{1,2})?", value or "")
    if not matches:
        return None
    try:
        return f"{float(matches[-1].replace(',', '')):.2f}"
    except ValueError:
        return None


def _fact_findings(content: str, workspace_id: str, db: Session) -> list[dict[str, Any]]:
    """Compare detected prices and product aliases only to explicitly approved facts."""
    facts = db.scalars(select(ApprovedFact).where(ApprovedFact.workspace_id == workspace_id)
        .order_by(ApprovedFact.fact_key, ApprovedFact.version_number.desc())).all()
    now = datetime.now(timezone.utc)
    active_by_key: dict[str, ApprovedFact] = {}
    all_by_key: dict[str, list[ApprovedFact]] = {}
    for fact in facts:
        all_by_key.setdefault(fact.fact_key, []).append(fact)
        start, end = _aware(fact.valid_from), _aware(fact.valid_until)
        if fact.status == "approved" and (start is None or start <= now) and (end is None or end >= now):
            active_by_key.setdefault(fact.fact_key, fact)

    output: list[dict[str, Any]] = []
    price_facts = [f for f in active_by_key.values() if f.fact_type == "price"]
    expired_prices = [f for f in facts if f.fact_type == "price" and f.status in {"approved", "superseded"}
                      and _aware(f.valid_until) is not None and _aware(f.valid_until) < now]
    # Match common currency-prefixed values. We do not infer that a price is stale unless an
    # approved source exists and the amount conflicts with it or its validity window expired.
    price_re = re.compile(r"(?:₹|INR\s?|Rs\.?\s?|\$|USD\s?|€|EUR\s?|£|GBP\s?)\s?\d[\d,]*(?:\.\d{1,2})?", re.I)
    price_rule = next((r for r in db.scalars(select(BrandRule).where(
        BrandRule.workspace_id == workspace_id, BrandRule.code == "PRC-002")).all()), None)
    seen_amounts: set[str] = set()
    for match in price_re.finditer(content):
        amount = _numeric_amount(match.group(0))
        if not amount or amount in seen_amounts:
            continue
        seen_amounts.add(amount)
        if not price_facts and not expired_prices:
            continue
        current_values = {_numeric_amount(f.canonical_value) for f in price_facts}
        if amount in current_values:
            continue
        expired_match = next((f for f in expired_prices if _numeric_amount(f.canonical_value) == amount), None)
        reference = expired_match or (price_facts[0] if price_facts else None)
        if not reference:
            continue
        status = "expired" if expired_match else "mismatch"
        reason = (f"The detected amount {match.group(0)} matches an approved fact whose validity window has expired."
                  if expired_match else f"The detected amount {match.group(0)} does not match the current approved price fact for {reference.entity_name or reference.fact_key}.")
        output.append({"rule_id": price_rule.id if price_rule else None,
            "severity": "warning", "finding_type": "pricing", "flagged_text": match.group(0),
            "page_number": 1, "location_bbox": None, "reasoning": reason,
            "suggested_fix": f"Verify against approved fact {reference.fact_key}: {reference.canonical_value}.",
            "evidence_fact_id": reference.id, "evidence_status": status})

    product_rule = next((r for r in db.scalars(select(BrandRule).where(
        BrandRule.workspace_id == workspace_id, BrandRule.code == "TERM-008")).all()), None)
    for fact in active_by_key.values():
        if fact.fact_type != "product_name":
            continue
        for alias in fact.aliases or []:
            if alias.strip() and alias.casefold() in content.casefold():
                output.append({"rule_id": product_rule.id if product_rule else None,
                    "severity": "warning", "finding_type": "terminology", "flagged_text": alias,
                    "page_number": 1, "location_bbox": None,
                    "reasoning": f"This alias conflicts with the approved product name {fact.canonical_value}.",
                    "suggested_fix": f"Use the approved product name: {fact.canonical_value}.",
                    "evidence_fact_id": fact.id, "evidence_status": "mismatch"})
    return output


def _rules_fingerprint(rules: list[BrandRule]) -> str:
    payload = [{"id": r.id, "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                "pattern": r.pattern, "active": r.is_active} for r in sorted(rules, key=lambda item: item.id)]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _persist_scan_findings(db: Session, user: User, doc: ContentDocument, rules: list[BrandRule],
                            proposed: list[dict[str, Any]], started_at: datetime, engine_mode: str = "deterministic") -> ScanRun:
    by_id = {rule.id: rule for rule in rules}
    scan = ScanRun(workspace_id=user.workspace_id, document_id=doc.id, initiated_by=user.id,
        engine_mode=engine_mode, ruleset_fingerprint=_rules_fingerprint(rules), status="completed",
        total_findings=len(proposed), started_at=started_at, completed_at=utcnow(),
        duration_ms=max(0, int((utcnow() - started_at).total_seconds() * 1000)))
    db.add(scan)
    db.flush()
    verified = 0
    unverifiable = 0
    for raw in proposed:
        item = dict(raw)
        fact_id = item.pop("evidence_fact_id", None)
        fact_status = item.pop("evidence_status", None)
        rule = by_id.get(item.get("rule_id"))
        version = _latest_rule_version(db, rule)
        finding = ReviewFinding(content_id=doc.id, rule_version_id=version.id if version else None, **item)
        db.add(finding)
        db.flush()
        if fact_id:
            fact = db.get(ApprovedFact, fact_id)
            if fact and fact.workspace_id == user.workspace_id:
                db.add(FindingEvidence(workspace_id=user.workspace_id, finding_id=finding.id,
                    scan_run_id=scan.id, source_kind="approved_fact", source_id=fact.id,
                    source_version=fact.version_number, source_label=f"{fact.source_document} · {fact.fact_key}",
                    source_quote=fact.source_quote, content_quote=finding.flagged_text,
                    locator={"page": fact.source_page} if fact.source_page else {},
                    verification_status=fact_status or "linked", match_score=1.0))
                verified += 1
        elif rule and version:
            # The evidence record proves provenance to the approved policy revision and
            # preserves the exact content excerpt; it does not claim legal truth by itself.
            grounded = bool(finding.flagged_text and finding.flagged_text.casefold() in doc.content_text.casefold())
            db.add(FindingEvidence(workspace_id=user.workspace_id, finding_id=finding.id,
                scan_run_id=scan.id, source_kind="brand_rule", source_id=rule.id,
                source_version=version.version_number, source_label=f"{rule.source_document} · {rule.code}",
                source_quote=version.snapshot.get("rule_clause", rule.rule_clause),
                content_quote=finding.flagged_text, locator={"page": finding.page_number, **(finding.location_bbox or {})},
                verification_status="grounded" if grounded else "unverifiable", match_score=1.0 if grounded else 0.0))
            if grounded: verified += 1
            else: unverifiable += 1
        else:
            unverifiable += 1
    scan.verified_evidence = verified
    scan.unverifiable_evidence = unverifiable
    _create_review_tasks(db, user, doc, proposed)
    return scan


def _create_review_tasks(db: Session, user: User, doc: ContentDocument, findings: list[dict[str, Any]]) -> None:
    routes: dict[str, list[str]] = {}
    for item in findings:
        kind = item.get("finding_type")
        severity = item.get("severity")
        if kind in {"claim", "legal"} or severity == "critical":
            routes.setdefault("SME / Legal", []).append(str(item.get("finding_type")))
        elif kind in {"pricing", "asset", "accessibility", "contrast"}:
            routes.setdefault("Manager", []).append(str(kind))
    for role, reasons in routes.items():
        exists = db.scalar(select(ReviewTask.id).where(ReviewTask.document_id == doc.id,
            ReviewTask.assigned_role == role, ReviewTask.status != "completed").limit(1))
        if exists:
            continue
        reviewer = db.scalar(select(User).where(User.workspace_id == user.workspace_id,
            User.role == role, User.is_active.is_(True)).order_by(User.created_at).limit(1))
        priority = "critical" if role == "SME / Legal" else "high"
        notify(db, user.workspace_id, [reviewer.id] if reviewer else workspace_admin_ids(db, user.workspace_id),
               "review_task", f"{priority.title()} review needed: {doc.filename}",
               "Review required for: " + ", ".join(sorted(set(reasons))), "document", doc.id, user.id)
        db.add(ReviewTask(workspace_id=user.workspace_id, document_id=doc.id, assigned_role=role,
            assigned_to=reviewer.id if reviewer else None,
            reason="Review required for: " + ", ".join(sorted(set(reasons))), priority=priority,
            due_at=utcnow() + timedelta(hours=24 if priority == "critical" else 72)))


def _fact_out(fact: ApprovedFact) -> dict[str, Any]:
    return {"id": fact.id, "fact_key": fact.fact_key, "fact_type": fact.fact_type,
        "entity_name": fact.entity_name, "canonical_value": fact.canonical_value,
        "currency": fact.currency, "unit": fact.unit, "aliases": fact.aliases,
        "source_document": fact.source_document, "source_quote": fact.source_quote,
        "source_document_id": fact.source_document_id, "source_verified": fact.source_verified, "source_page": fact.source_page,
        "valid_from": fact.valid_from, "valid_until": fact.valid_until, "status": fact.status,
        "version_number": fact.version_number, "supersedes_id": fact.supersedes_id,
        "created_by": fact.created_by, "approved_by": fact.approved_by,
        "approved_at": fact.approved_at, "created_at": fact.created_at}


def _seed_workspace_rules(db: Session, workspace_id: str) -> None:
    """Seed the approved starter rule set into one workspace exactly once."""
    for item in SEED_RULES:
        existing = db.scalar(select(BrandRule).where(
            BrandRule.workspace_id == workspace_id, BrandRule.code == item["code"]))
        if not existing:
            vector, vector_model = embed_with_model(f"{item['title']} {item['category']} {item['rule_clause']}")
            db.add(BrandRule(workspace_id=workspace_id, **item, embedding=vector, embedding_model=vector_model))


def _seed() -> None:
    run_migrations(engine)
    _ensure_user_workspace_columns()
    _ensure_round3_columns()
    if DATABASE_URL.startswith("postgresql"):
        try:
            with engine.begin() as conn:
                conn.execute(text("CREATE INDEX IF NOT EXISTS brand_rules_embedding_hnsw ON brand_rules USING hnsw (embedding vector_cosine_ops)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS guideline_chunks_embedding_hnsw ON guideline_chunks USING hnsw (embedding vector_cosine_ops)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS guideline_chunks_content_fts ON guideline_chunks USING gin (to_tsvector('english', content))"))
        except Exception:
            logger.exception("Could not create pgvector HNSW index; rule search will still have a hybrid application-level fallback")
    with SessionLocal() as db:
        # Demo accounts must never be created in a public production deployment.
        if APP_ENV.lower() in {"development", "demo", "test"}:
            set_workspace_context(db, WORKSPACE_ID)
            users = [
                ("ContexA Admin", "admin@contexa.local", "Brand Admin", "ContexA!2026"),
                ("Alex Morgan", "manager@contexa.local", "Manager", "Manager!2026"),
                ("Jordan Lee", "creator@contexa.local", "Creator", "Creator!2026"),
                ("Sam Rivera", "legal@contexa.local", "SME / Legal", "Legal!2026"),
            ]
            for name, email, role, password in users:
                existing = db.scalar(select(User).where(User.email == email))
                if not existing:
                    existing = User(name=name, email=email, role=role, workspace_id=WORKSPACE_ID,
                        workspace_name="ContexA Demo Workspace", password_hash=hash_password(password),
                        is_email_verified=True, email_verified_at=utcnow())
                    db.add(existing)
                elif not existing.workspace_id:
                    existing.workspace_id = WORKSPACE_ID
                    existing.workspace_name = "ContexA Demo Workspace"
                existing.is_email_verified = True
                existing.email_verified_at = existing.email_verified_at or utcnow()
            _seed_workspace_rules(db, WORKSPACE_ID)
        for workspace in db.scalars(select(User.workspace_id).distinct()).all():
            set_workspace_context(db, workspace)
            _ensure_rule_versions(db, workspace)
        db.commit()


def startup() -> None:
    if AUTH_MODE not in {"local", "hybrid", "supabase"}:
        raise RuntimeError("AUTH_MODE must be one of: local, hybrid, supabase.")
    if AUTH_MODE in {"hybrid", "supabase"}:
        if not (SUPABASE_URL and SUPABASE_JWT_ISSUER and SUPABASE_JWKS_URL):
            raise RuntimeError(f"AUTH_MODE={AUTH_MODE} requires SUPABASE_URL, SUPABASE_JWT_ISSUER and SUPABASE_JWKS_URL.")
        if not SUPABASE_JWT_ALGORITHMS or not set(SUPABASE_JWT_ALGORITHMS).issubset({"ES256", "RS256"}):
            raise RuntimeError("Supabase Auth must use asymmetric ES256 or RS256 JWT signing keys.")
        expected_issuer = f"{SUPABASE_URL}/auth/v1"
        if SUPABASE_JWT_ISSUER != expected_issuer:
            raise RuntimeError("SUPABASE_JWT_ISSUER must match SUPABASE_URL/auth/v1 for the same project.")
        if SUPABASE_SESSION_CHECK_REQUIRED and not SUPABASE_SESSION_DATABASE_URL:
            raise RuntimeError("Supabase mode requires SUPABASE_SESSION_DATABASE_URL for immediate session revocation checks.")
        if SUPABASE_SESSION_CHECK_REQUIRED and not SUPABASE_PUBLISHABLE_KEY:
            raise RuntimeError("Supabase mode requires SUPABASE_PUBLISHABLE_KEY so the API can revoke the current Auth session on logout.")
    if APP_ENV.lower() == "production":
        _validate_production_cors_origins()
        if len(SECRET_KEY) < 32 or SECRET_KEY == "dev-only-change-this-secret-before-deploying" or "replace-with" in SECRET_KEY.lower():
            raise RuntimeError("Production requires a strong SECRET_KEY (32+ random characters). Configure it in your hosting environment.")
        if TRUST_SIGNING_PROVIDER == "aws_kms":
            if not TRUST_KMS_KEY_ID:
                raise RuntimeError("TRUST_SIGNING_PROVIDER=aws_kms requires TRUST_KMS_KEY_ID and an ECS/task IAM role with kms:Sign and kms:GetPublicKey.")
        elif (not os.getenv("TRUST_PASSPORT_SIGNING_KEY")
                or len(TRUST_PASSPORT_SIGNING_KEY) < 32
                or "replace-with" in TRUST_PASSPORT_SIGNING_KEY.lower()):
            raise RuntimeError("Production requires a dedicated stable TRUST_PASSPORT_SIGNING_KEY (32+ random characters) or an AWS KMS asymmetric signing key.")
        if TRUST_ARCHIVE_REQUIRED and (not EVIDENCE_ARCHIVE_BUCKET or EVIDENCE_ARCHIVE_RETENTION_DAYS < 1):
            raise RuntimeError("TRUST_ARCHIVE_REQUIRED requires EVIDENCE_ARCHIVE_BUCKET and positive Object Lock retention days.")
        if EVIDENCE_ARCHIVE_MODE not in {"GOVERNANCE", "COMPLIANCE"}:
            raise RuntimeError("EVIDENCE_ARCHIVE_MODE must be GOVERNANCE or COMPLIANCE.")
        app_url = urlsplit(PUBLIC_APP_URL)
        if app_url.scheme != "https" or not app_url.netloc:
            raise RuntimeError("Production requires PUBLIC_APP_URL to be the deployed HTTPS frontend origin used by Trust Passport QR links.")
        if CLOUDFLARE_EDGE_ENABLED and not CLOUDFLARE_ORIGIN_SHARED_SECRET:
            raise RuntimeError("CLOUDFLARE_EDGE_ENABLED requires CLOUDFLARE_ORIGIN_SHARED_SECRET to lock the API origin to the Worker.")
        if DATABASE_URL.startswith("sqlite"):
            raise RuntimeError("Production must use a persistent PostgreSQL DATABASE_URL; SQLite/local ephemeral storage is not supported for public accounts.")
        if not ENABLE_POSTGRES_RLS:
            raise RuntimeError("Production requires ENABLE_POSTGRES_RLS=true. Refusing to start without database tenant isolation.")
        if AUTH_MODE != "supabase" and (not EMAIL_VERIFICATION_REQUIRED or not (SMTP_HOST and SMTP_FROM_EMAIL)):
            raise RuntimeError("Production local/hybrid registration requires EMAIL_VERIFICATION_REQUIRED=true and configured SMTP_HOST/SMTP_FROM_EMAIL.")
        if AUTH_MODE != "supabase" and not (SMTP_USE_TLS or SMTP_USE_SSL):
            raise RuntimeError("Production SMTP must use STARTTLS or implicit TLS. Plaintext SMTP is not allowed.")
        if AUTH_MODE != "supabase" and SMTP_USE_TLS and SMTP_USE_SSL:
            raise RuntimeError("Choose either SMTP STARTTLS or SMTP implicit SSL, not both.")
        if AUTH_MODE != "supabase" and bool(SMTP_USERNAME) != bool(SMTP_PASSWORD):
            raise RuntimeError("Configure both SMTP_USERNAME and SMTP_PASSWORD, or leave both blank for a trusted relay.")
        if REQUIRE_PRIVATE_OBJECT_STORAGE and not S3_BUCKET:
            raise RuntimeError("Production requires private S3-compatible object storage. Configure S3_BUCKET and provider credentials.")
        if not S3_BUCKET and not STORE_UPLOADS_IN_DATABASE:
            raise RuntimeError("Production uploads need S3_BUCKET or STORE_UPLOADS_IN_DATABASE=true; ephemeral local disk is not durable.")
        if REQUIRE_MALWARE_SCAN and UPLOAD_SCAN_MODE != "clamd":
            raise RuntimeError("Production requires UPLOAD_SCAN_MODE=clamd when REQUIRE_MALWARE_SCAN=true.")
    if bool(S3_ACCESS_KEY_ID) != bool(S3_SECRET_ACCESS_KEY):
        raise RuntimeError("Configure both S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY, or leave both blank to use the provider's workload identity.")
    if S3_BUCKET and not os.getenv("S3_ENDPOINT_URL") and os.getenv("S3_FORCE_PATH_STYLE", "false").lower() in {"1", "true", "yes"}:
        logger.warning("S3_FORCE_PATH_STYLE is enabled without a custom endpoint; verify this matches your S3 provider.")
    prepare_database()
    _seed()
    # Expired one-time tokens and stale hashed rate-limit state are pruned on startup.
    with SessionLocal() as maintenance_db:
        cutoff_tokens = utcnow() - timedelta(days=AUTH_TOKEN_RETENTION_DAYS)
        cutoff_attempts = utcnow() - timedelta(days=LOGIN_ATTEMPT_RETENTION_DAYS)
        maintenance_db.query(AuthActionToken).filter(AuthActionToken.expires_at < cutoff_tokens).delete(synchronize_session=False)
        maintenance_db.query(LoginAttempt).filter(LoginAttempt.updated_at < cutoff_attempts).delete(synchronize_session=False)
        maintenance_db.commit()
    if DATABASE_URL.startswith("postgresql") and ENABLE_POSTGRES_RLS:
        enable_postgres_rls()
        from .database import verify_postgres_rls
        verify_postgres_rls(require_safe_role=APP_ENV.lower() == "production")



def _retrieve_ai_candidates(db: Session, content: str, rules: list[BrandRule], workspace_id: str) -> list[BrandRule]:
    """Retrieve a small RAG context using pgvector cosine distance plus lexical reranking.

    SQLite local mode uses deterministic hashed embeddings and the same hybrid ranking in Python.
    PostgreSQL mode first asks pgvector for nearest neighbors, then reranks them with lexical overlap.
    """
    active = [r for r in rules if r.is_active]
    if not active:
        return []
    query_text = content[:12000]
    query_vector, query_model = embed_with_model(query_text)
    compatible = [r for r in active if (r.embedding_model or "hashed-token-v1") == query_model]
    selected: list[BrandRule] = []
    if DATABASE_URL.startswith("postgresql") and compatible:
        try:
            vector_literal = "[" + ",".join(f"{v:.8f}" for v in query_vector) + "]"
            result = db.execute(text("""SELECT id FROM brand_rules
                WHERE workspace_id = :workspace_id AND is_active = TRUE AND embedding IS NOT NULL
                  AND embedding_model = :embedding_model
                ORDER BY embedding <=> CAST(:query_vector AS vector) LIMIT 12"""),
                {"workspace_id": workspace_id, "query_vector": vector_literal, "embedding_model": query_model}).all()
            by_id = {r.id: r for r in compatible}
            selected = [by_id[str(row[0])] for row in result if str(row[0]) in by_id]
        except Exception:
            logger.exception("pgvector retrieval failed; using local hybrid reranking")
    # Exact token overlap remains available even if an embedder model has not been indexed yet.
    lexical = sorted(active, key=lambda r: hybrid_score(query_text, f"{r.title} {r.category} {r.rule_clause}",
        r.embedding if (r.embedding_model or "hashed-token-v1") == query_model else None, query_vector), reverse=True)[:8]
    union: dict[str, BrandRule] = {r.id: r for r in [*selected, *lexical]}
    return sorted(union.values(), key=lambda r: hybrid_score(query_text, f"{r.title} {r.category} {r.rule_clause}",
        r.embedding if (r.embedding_model or "hashed-token-v1") == query_model else None, query_vector), reverse=True)[:5]

def _finding_out(finding: ReviewFinding) -> dict[str, Any]:
    return {
        "id": finding.id, "content_id": finding.content_id, "rule_id": finding.rule_id, "rule_version_id": finding.rule_version_id,
        "rule_code": finding.rule.code if finding.rule else None,
        "rule_title": finding.rule.title if finding.rule else "Unverifiable AI result",
        "severity": finding.severity, "finding_type": finding.finding_type,
        "flagged_text": finding.flagged_text, "page_number": finding.page_number,
        "location_bbox": finding.location_bbox, "reasoning": finding.reasoning,
        "suggested_fix": finding.suggested_fix, "applied_text": finding.applied_text, "status": finding.status,
        "dismissal_reason": finding.dismissal_reason,
        "created_at": finding.created_at, "updated_at": finding.updated_at,
    }


def _document_out(doc: ContentDocument, db: Session) -> dict[str, Any]:
    findings = db.scalars(select(ReviewFinding).where(ReviewFinding.content_id == doc.id)).all()
    creator = db.get(User, doc.created_by)
    return {
        "id": doc.id, "filename": doc.filename, "content_type": doc.content_type,
        "page_count": doc.page_count, "status": doc.status, "compliance_score": doc.compliance_score,
        "size_bytes": doc.size_bytes, "sha256": doc.sha256, "scan_status": doc.scan_status, "created_by": doc.created_by,
        "creator_name": creator.name if creator else "Unknown user", "created_at": doc.created_at,
        "updated_at": doc.updated_at, "findings_count": sum(1 for f in findings if f.status == "open"),
        "critical_count": sum(1 for f in findings if f.status == "open" and f.severity == "critical"),
    }


def _open_findings(db: Session, doc_id: str) -> list[ReviewFinding]:
    return db.scalars(select(ReviewFinding).options(joinedload(ReviewFinding.rule))
        .where(ReviewFinding.content_id == doc_id, ReviewFinding.status == "open")
        .order_by(ReviewFinding.severity.desc(), ReviewFinding.created_at.asc())).all()


def _recompute_document(doc: ContentDocument, db: Session) -> None:
    open_findings = db.scalars(select(ReviewFinding).where(ReviewFinding.content_id == doc.id, ReviewFinding.status == "open")).all()
    penalties = sum(22 if f.severity == "critical" else 8 if f.severity == "warning" else 2 for f in open_findings)
    doc.compliance_score = max(0, 100 - penalties)
    critical_open = sum(1 for f in open_findings if f.severity == "critical")
    if doc.status != "PUBLISH_READY":
        doc.status = "IN_REVIEW" if critical_open else "READY_FOR_SIGNOFF"
    doc.updated_at = utcnow()


def _get_doc(doc_id: str, db: Session, user: User) -> ContentDocument:
    doc = db.get(ContentDocument, doc_id)
    if not doc or doc.workspace_id != user.workspace_id:
        raise HTTPException(status_code=404, detail="Document not found.")
    return doc


@app.get("/api/health")
def health() -> dict[str, Any]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("Readiness check could not reach the application database: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Application database is unavailable.") from exc
    local_status = local_ai_status()
    return {"status": "ok", "database_ready": True, "app": APP_NAME, "environment": APP_ENV,
            "ai_configured": bool(local_status.get("model_available") or ANTHROPIC_API_KEY),
            "ai_model": OLLAMA_MODEL if local_status.get("model_available") else (ANTHROPIC_MODEL if ANTHROPIC_API_KEY else None),
            "local_ai": local_status,
            "database": "postgresql" if DATABASE_URL.startswith("postgresql") else "sqlite",
            "account_security": {"email_verification_required": EMAIL_VERIFICATION_REQUIRED, "signup_open": ALLOW_SIGNUP, "password_hash": "Argon2id" if __import__("app.security", fromlist=["_ARGON2"])._ARGON2 is not None else "PBKDF2-SHA256 fallback"},
            "object_storage": {"provider": "s3-compatible" if S3_BUCKET else ("database" if STORE_UPLOADS_IN_DATABASE else "private-local"),
                               "durable": bool(S3_BUCKET or STORE_UPLOADS_IN_DATABASE)},
            "upload_security": {"signature_validation": True, "malware_scanning": UPLOAD_SCAN_MODE == "clamd",
                                "scanner_mode": UPLOAD_SCAN_MODE, "max_upload_mb": MAX_UPLOAD_MB},
            "tenant_isolation": {"application_workspace_checks": True, "postgres_rls_enabled": ENABLE_POSTGRES_RLS and DATABASE_URL.startswith("postgresql")},
            "security_headers_enabled": SECURITY_HEADERS_ENABLED,
            "cloudflare": {"edge_gateway_enabled": CLOUDFLARE_EDGE_ENABLED,
                           "origin_auth_enabled": bool(CLOUDFLARE_EDGE_ENABLED and CLOUDFLARE_ORIGIN_SHARED_SECRET),
                           "turnstile_enabled": bool(TURNSTILE_SECRET_KEY),
                           "r2_enabled": bool(S3_BUCKET and "r2.cloudflarestorage.com" in os.getenv("S3_ENDPOINT_URL", "")),
                           "ai_gateway_enabled": bool(ANTHROPIC_BASE_URL and "gateway.ai.cloudflare.com" in ANTHROPIC_BASE_URL)} }


def _auth_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _new_auth_token(db: Session, purpose: str, email: str, user_id: str | None,
                    workspace_id: str | None, payload: dict[str, Any] | None = None) -> str:
    raw = secrets.token_urlsafe(36)
    db.add(AuthActionToken(workspace_id=workspace_id, user_id=user_id, email=email.lower(),
        purpose=purpose, token_hash=_auth_digest(raw), payload=payload or {},
        expires_at=utcnow() + timedelta(minutes=AUTH_TOKEN_MINUTES)))
    return raw


def _smtp_ready() -> bool:
    return bool(SMTP_HOST and SMTP_FROM_EMAIL)


def _send_account_link(email: str, subject: str, purpose: str, token: str) -> str | None:
    link = f"{PUBLIC_APP_URL}/?{purpose}_token={token}"
    if not _smtp_ready():
        if APP_ENV.lower() == "production":
            logger.warning("SMTP is not configured; unable to deliver %s email to %s", purpose, email)
            return None
        logger.info("Development %s link for %s: %s", purpose, email, link)
        return link
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_EMAIL}>"
    message["To"] = email
    message.set_content(f"Use this one-time ContexA link within {AUTH_TOKEN_MINUTES} minutes:\n\n{link}\n\nIf you did not request this, you can ignore this email.")
    try:
        if SMTP_USE_SSL:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=12) as server:
                if SMTP_USERNAME:
                    server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(message)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=12) as server:
                server.ehlo()
                if SMTP_USE_TLS:
                    server.starttls()
                    server.ehlo()
                if SMTP_USERNAME:
                    server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(message)
    except Exception as exc:
        logger.exception("Could not send %s email", purpose)
        raise HTTPException(status_code=503, detail="Email delivery is temporarily unavailable. Please try again later.") from exc
    return None


def _consume_auth_token(db: Session, raw: str, purpose: str) -> AuthActionToken:
    token = db.scalar(select(AuthActionToken).where(AuthActionToken.token_hash == _auth_digest(raw),
        AuthActionToken.purpose == purpose, AuthActionToken.consumed_at.is_(None)))
    if not token or _aware(token.expires_at) < utcnow():
        raise HTTPException(status_code=400, detail="This link is invalid or expired. Request a new one.")
    token.consumed_at = utcnow()
    return token


def _consume_rate_limit(db: Session, identity: str, limit: int, window_minutes: int, message: str) -> None:
    """Persistent per-identity throttling for public auth actions."""
    now = utcnow()
    key = _auth_digest(identity)
    row = db.scalar(select(LoginAttempt).where(LoginAttempt.identity_hash == key))
    if row and row.locked_until and _aware(row.locked_until) > now:
        raise HTTPException(status_code=429, detail=message)
    if not row:
        row = LoginAttempt(identity_hash=key, failures=0, window_started_at=now)
        db.add(row)
    if _aware(row.window_started_at) + timedelta(minutes=window_minutes) < now:
        row.failures = 0; row.window_started_at = now; row.locked_until = None
    row.failures += 1
    if row.failures > limit:
        row.locked_until = now + timedelta(minutes=window_minutes)
        db.commit()
        raise HTTPException(status_code=429, detail=message)
    db.commit()


def _verify_turnstile(token: str | None, request: Request, action: str) -> None:
    """Fail closed when Turnstile is configured; never trust a browser token alone."""
    if not TURNSTILE_SECRET_KEY:
        return
    if not token:
        raise HTTPException(status_code=400, detail="Complete the anti-bot verification and try again.")
    remote_ip = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else None)
    verification_payload = {"secret": TURNSTILE_SECRET_KEY, "response": token}
    if remote_ip:
        verification_payload["remoteip"] = remote_ip
    verification_request = URLRequest(
        "https://challenges.cloudflare.com/turnstile/v0/siteverify",
        data=json.dumps(verification_payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urlopen(verification_request, timeout=6) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (URLError, HTTPError, TimeoutError, OSError, ValueError) as exc:
        logger.warning("Cloudflare Turnstile validation unavailable (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Anti-bot verification is temporarily unavailable. Please retry.") from exc
    if not isinstance(result, dict) or not result.get("success"):
        raise HTTPException(status_code=400, detail="Anti-bot verification failed. Please try again.")
    hostname = str(result.get("hostname", "")).lower()
    if TURNSTILE_EXPECTED_HOSTNAME and hostname != TURNSTILE_EXPECTED_HOSTNAME:
        raise HTTPException(status_code=400, detail="Anti-bot verification was issued for an unexpected hostname.")
    returned_action = result.get("action")
    if returned_action != action:
        raise HTTPException(status_code=400, detail="Anti-bot verification action did not match this request.")


@app.post("/api/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    if AUTH_MODE == "supabase":
        raise HTTPException(status_code=403, detail="Local password authentication is disabled. Sign in through the configured Supabase identity provider.")
    _verify_turnstile(payload.turnstile_token, request, "auth")
    email = payload.email.strip().lower()
    identity_hash = _auth_digest(f"{email}|{request.client.host if request.client else 'unknown'}")
    attempt = db.scalar(select(LoginAttempt).where(LoginAttempt.identity_hash == identity_hash))
    now = utcnow()
    if attempt and attempt.locked_until and _aware(attempt.locked_until) > now:
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again after the temporary lock expires.")
    user = db.scalar(select(User).where(User.email == email))
    if not user or not verify_password(payload.password, user.password_hash):
        if not attempt:
            attempt = LoginAttempt(identity_hash=identity_hash, failures=0, window_started_at=now)
            db.add(attempt)
        if _aware(attempt.window_started_at) + timedelta(minutes=LOGIN_LOCK_MINUTES) < now:
            attempt.failures = 0; attempt.window_started_at = now
        attempt.failures += 1
        if attempt.failures >= LOGIN_MAX_FAILURES:
            attempt.locked_until = now + timedelta(minutes=LOGIN_LOCK_MINUTES)
        db.commit()
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    if EMAIL_VERIFICATION_REQUIRED and not user.is_email_verified:
        raise HTTPException(status_code=403, detail="Verify your email address before signing in.")
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
        db.commit()
    if attempt:
        attempt.failures = 0; attempt.locked_until = None; attempt.window_started_at = now
        db.commit()
    return {"access_token": create_access_token(user), "token_type": "bearer", "user": user}


@app.post("/api/auth/register", status_code=201)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    """Create an isolated workspace. Public registration can never assign a privileged team role."""
    if AUTH_MODE == "supabase":
        raise HTTPException(status_code=403, detail="Public ContexA password registration is disabled. Create or accept an invitation through the configured identity provider.")
    _verify_turnstile(payload.turnstile_token, request, "auth")
    _consume_rate_limit(db, f"signup|{request.client.host if request.client else 'unknown'}", SIGNUP_MAX_PER_IP, SIGNUP_WINDOW_MINUTES, "Too many new accounts were requested from this network. Try again later.")
    if not ALLOW_SIGNUP:
        raise HTTPException(status_code=403, detail="New account registration is currently closed.")
    if EMAIL_VERIFICATION_REQUIRED and APP_ENV.lower() == "production" and not _smtp_ready():
        raise HTTPException(status_code=503, detail="Email verification is enabled but SMTP is not configured. Contact the administrator.")
    name = " ".join(payload.name.split()).strip()
    email = payload.email.strip().lower()
    workspace_name = " ".join((payload.workspace_name or "").split()).strip()
    if len(name) < 2 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or len(email) > 254:
        raise HTTPException(status_code=422, detail="Enter a valid name and email address.")
    if len(payload.password) < 12 or not any(ch.isalpha() for ch in payload.password) or not any(ch.isdigit() for ch in payload.password):
        raise HTTPException(status_code=422, detail="Use at least 12 characters, including a letter and a number.")
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists. Sign in instead.")
    workspace_id = f"ws-{uuid.uuid4()}"
    set_workspace_context(db, workspace_id)
    workspace_name = workspace_name[:140] or f"{name.split()[0]}'s Workspace"
    verified = not EMAIL_VERIFICATION_REQUIRED
    new_user = User(name=name, email=email, role="Brand Admin", workspace_id=workspace_id,
        workspace_name=workspace_name, password_hash=hash_password(payload.password), is_active=True,
        is_email_verified=verified, email_verified_at=utcnow() if verified else None)
    db.add(new_user); db.flush()
    _seed_workspace_rules(db, workspace_id); _ensure_rule_versions(db, workspace_id)
    debug_link = None
    if EMAIL_VERIFICATION_REQUIRED:
        token = _new_auth_token(db, "verify-email", email, new_user.id, workspace_id)
        db.flush()
    _audit(db, new_user, "account.created", "user", new_user.id,
        {"email": email, "workspace_name": workspace_name, "signup": "self_service", "email_verified": verified})
    db.commit(); db.refresh(new_user)
    if EMAIL_VERIFICATION_REQUIRED:
        debug_link = _send_account_link(email, "Verify your ContexA account", "verify-email", token)
        return {"verification_required": True, "message": "Your workspace is created. Verify your email before signing in.",
                "debug_link": debug_link}
    return {"access_token": create_access_token(new_user), "token_type": "bearer", "user": new_user}


@app.post("/api/auth/verify-email")
def verify_email(payload: TokenRequest, db: Session = Depends(get_db)):
    token = _consume_auth_token(db, payload.token, "verify-email")
    user = db.get(User, token.user_id) if token.user_id else None
    if not user:
        raise HTTPException(status_code=400, detail="The account for this link no longer exists.")
    set_workspace_context(db, user.workspace_id)
    user.is_email_verified = True; user.email_verified_at = utcnow()
    _audit(db, user, "account.email_verified", "user", user.id, {})
    db.commit()
    return {"verified": True, "message": "Email verified. You can now sign in."}


@app.post("/api/auth/password/forgot")
def forgot_password(payload: dict[str, str], request: Request, db: Session = Depends(get_db)):
    if AUTH_MODE == "supabase":
        raise HTTPException(status_code=403, detail="Password recovery is managed by Supabase Auth for this deployment.")
    email = str(payload.get("email", "")).strip().lower()
    _consume_rate_limit(db, f"password-reset|{email}|{request.client.host if request.client else 'unknown'}", PASSWORD_RESET_MAX_PER_IP, 60, "Too many recovery requests. Try again later.")
    generic = {"message": "If an account exists for that email, password recovery instructions will be sent."}
    user = db.scalar(select(User).where(User.email == email, User.is_active.is_(True)))
    if not user:
        return generic
    token_value = _new_auth_token(db, "password-reset", user.email, user.id, user.workspace_id)
    _audit(db, user, "account.password_reset_requested", "user", user.id, {})
    db.commit()
    debug_link = _send_account_link(user.email, "Reset your ContexA password", "password-reset", token_value)
    if debug_link:
        return {**generic, "debug_link": debug_link}
    return generic


@app.post("/api/auth/password/reset")
def reset_password(payload: PasswordResetRequest, db: Session = Depends(get_db)):
    if AUTH_MODE == "supabase":
        raise HTTPException(status_code=403, detail="Password recovery is managed by Supabase Auth for this deployment.")
    if len(payload.password) < 12 or not any(c.isalpha() for c in payload.password) or not any(c.isdigit() for c in payload.password):
        raise HTTPException(status_code=422, detail="Use at least 12 characters, including a letter and a number.")
    token = _consume_auth_token(db, payload.token, "password-reset")
    user = db.get(User, token.user_id) if token.user_id else None
    if not user or not user.is_active:
        raise HTTPException(status_code=400, detail="The account for this link is unavailable.")
    set_workspace_context(db, user.workspace_id)
    user.password_hash = hash_password(payload.password)
    user.token_version = int(user.token_version or 0) + 1
    _audit(db, user, "account.password_reset_completed", "user", user.id, {})
    db.commit()
    return {"reset": True, "message": "Password updated. Sign in with your new password."}


@app.post("/api/invitations", status_code=201)
def create_invitation(payload: InvitationCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("Brand Admin"))):
    email = payload.email.strip().lower()
    if APP_ENV.lower() == "production" and not _smtp_ready():
        raise HTTPException(status_code=503, detail="Configure SMTP before sending workspace invitations.")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=409, detail="This email already has a ContexA account.")
    token_value = _new_auth_token(db, "workspace-invite", email, None, user.workspace_id,
        {"role": payload.role, "workspace_name": user.workspace_name})
    _audit(db, user, "workspace.invitation_created", "invitation", _auth_digest(token_value)[:36], {"email": email, "role": payload.role})
    db.commit()
    debug_link = _send_account_link(email, f"Invitation to {user.workspace_name}", "workspace-invite", token_value)
    return {"invited": True, "email": email, "role": payload.role,
            "debug_link": debug_link, "message": "Invitation created. Deliver the one-time link to the invited teammate."}


@app.post("/api/invitations/accept", status_code=201)
def accept_invitation(payload: InvitationAccept, db: Session = Depends(get_db)):
    name = " ".join(payload.name.split()).strip()
    if len(payload.password) < 12 or not any(c.isalpha() for c in payload.password) or not any(c.isdigit() for c in payload.password):
        raise HTTPException(status_code=422, detail="Use at least 12 characters, including a letter and a number.")
    token = _consume_auth_token(db, payload.token, "workspace-invite")
    if db.scalar(select(User.id).where(User.email == token.email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    workspace_owner = db.scalar(select(User).where(User.workspace_id == token.workspace_id, User.role == "Brand Admin"))
    if not workspace_owner:
        raise HTTPException(status_code=400, detail="The inviting workspace is no longer available.")
    set_workspace_context(db, token.workspace_id or "")
    invited = User(name=name, email=token.email, role=token.payload.get("role", "Creator"),
        workspace_id=token.workspace_id, workspace_name=token.payload.get("workspace_name", workspace_owner.workspace_name),
        password_hash=hash_password(payload.password), is_active=True, is_email_verified=True, email_verified_at=utcnow())
    db.add(invited); db.flush()
    _audit(db, invited, "workspace.invitation_accepted", "user", invited.id, {"role": invited.role})
    db.commit(); db.refresh(invited)
    return {"access_token": create_access_token(invited), "token_type": "bearer", "user": invited}


@app.get("/api/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@app.post("/api/auth/logout")
def logout(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    user: User = Depends(get_current_user),
):
    """Revoke the current provider session or increment the local token version."""
    raw_token = credentials.credentials if credentials else ""
    if AUTH_MODE == "supabase" or (AUTH_MODE == "hybrid" and raw_token.count(".") == 2):
        if not raw_token:
            raise HTTPException(status_code=401, detail="Sign in to continue.")
        revoke_supabase_session(raw_token)
        _audit(db, user, "account.supabase_session_revoked", "user", user.id, {"scope": "local"})
        db.commit()
        return {"logged_out": True, "message": "The current Supabase Auth session was revoked."}
    user.token_version = int(user.token_version or 0) + 1
    _audit(db, user, "account.sessions_revoked", "user", user.id, {"reason": "user_logout"})
    db.commit()
    return {"logged_out": True, "message": "All existing local sessions for this account have been revoked."}


@app.post("/api/users/{user_id}/deactivate")
def deactivate_user(user_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("Brand Admin"))):
    target = db.scalar(select(User).where(User.id == user_id, User.workspace_id == user.workspace_id))
    if not target:
        raise HTTPException(status_code=404, detail="Workspace member not found.")
    if target.id == user.id:
        raise HTTPException(status_code=422, detail="You cannot deactivate your own account.")
    target.is_active = False
    target.token_version = int(target.token_version or 0) + 1
    _audit(db, user, "workspace.member_deactivated", "user", target.id, {"email": target.email})
    db.commit()
    return {"deactivated": True, "user_id": target.id}


@app.get("/api/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), user: User = Depends(require_roles("Brand Admin"))):
    return db.scalars(select(User).where(User.workspace_id == user.workspace_id).order_by(User.name)).all()


@app.post("/api/users", response_model=UserOut, status_code=201)
def create_user(payload: dict[str, Any], db: Session = Depends(get_db), user: User = Depends(require_roles("Brand Admin"))):
    name, email, password, role = (str(payload.get(k, "")).strip() for k in ("name", "email", "password", "role"))
    if not name or not email or len(password) < 10 or role not in ROLES:
        raise HTTPException(status_code=422, detail="Name, valid email, a 10+ character password and a supported role are required.")
    if db.scalar(select(User).where(User.email == email.lower())):
        raise HTTPException(status_code=409, detail="A user with this email already exists.")
    new_user = User(name=name, email=email.lower(), password_hash=hash_password(password), role=role, workspace_id=user.workspace_id, workspace_name=user.workspace_name)
    db.add(new_user); db.flush()
    _audit(db, user, "user.created", "user", new_user.id, {"email": new_user.email, "role": new_user.role})
    db.commit(); db.refresh(new_user)
    return new_user


@app.post("/api/demo/seed")
def seed_demo_workspace(db: Session = Depends(get_db), user: User = Depends(require_roles("Brand Admin"))):
    """Create realistic demo assets for presentations without calling any AI provider.

    This endpoint is restricted to local/demo/test environments and is idempotent by filename.
    All findings are created through the deterministic inspection engine against active rules.
    """
    if APP_ENV.lower() not in {"development", "demo", "test"}:
        raise HTTPException(status_code=404, detail="Demo seeding is disabled outside local/demo environments.")

    samples = [
        ("DEMO_Q4_Launch_Campaign.txt",
         "Campaign headline: Contexa is the #1 fastest platform to boost revenue by 400%.\n\n"
         "Our revolutionary platform is only $19/month — save 30% today!\n\n"
         "Review brief: verify the evidence for every quantified outcome, confirm the active campaign price and terms, and replace unapproved superlatives before publishing."),
        ("DEMO_Product_Naming_Review.txt",
         "Product announcement: Contexa Cloud brings product teams into one shared workspace.\n\n"
         "Context A makes collaboration simple. Our world-class experience helps every team move faster.\n\n"
         "Review brief: use the approved spelling ContexA and replace unsubstantiated superlatives with specific product capabilities."),
        ("DEMO_Pricing_Refresh.txt",
         "Pricing page draft: The annual plan is only $49/month. Save 25% today with our current launch offer.\n\n"
         "Review brief: compare the price, discount, eligibility and expiration date with the current approved price book before publication."),
    ]
    active_rules = db.scalars(select(BrandRule).where(
        BrandRule.workspace_id == user.workspace_id, BrandRule.is_active.is_(True)
    )).all()
    existing_names = set(db.scalars(select(ContentDocument.filename).where(
        ContentDocument.workspace_id == user.workspace_id,
        ContentDocument.filename.in_([name for name, _ in samples])
    )).all())
    created = 0
    for filename, content in samples:
        if filename in existing_names:
            continue
        data = content.encode("utf-8")
        stored_path = store_bytes(data, f"demo-{uuid.uuid4()}.txt", "text/plain")
        pages = [{"page": 1, "text": content, "spans": []}]
        doc = ContentDocument(
            id=str(uuid.uuid4()), workspace_id=user.workspace_id, filename=filename,
            stored_path=stored_path, content_type="text/plain", content_text=content,
            pages_json=pages, page_count=1, status="IN_REVIEW", compliance_score=100,
            size_bytes=len(data), created_by=user.id,
        )
        db.add(doc); db.flush()
        # Passing [] explicitly guarantees the showcase is reproducible and never contacts Ollama/Claude.
        proposed = inspect_content(content, pages, active_rules, ai_candidates=[])
        for item in proposed:
            db.add(ReviewFinding(content_id=doc.id, **item))
        db.flush(); _recompute_document(doc, db)
        _audit(db, user, "demo.document_seeded", "document", doc.id,
               {"filename": filename, "finding_count": len(proposed), "review_mode": "deterministic_demo"})
        created += 1
    db.flush()
    _audit(db, user, "demo.workspace_prepared", "workspace", user.workspace_id,
           {"created_documents": created, "ai_used": False})
    db.commit()
    documents = db.scalars(select(ContentDocument).where(
        ContentDocument.workspace_id == user.workspace_id,
        ContentDocument.filename.in_([name for name, _ in samples])
    ).order_by(ContentDocument.filename)).all()
    return {
        "created_documents": created,
        "documents": [_document_out(doc, db) for doc in documents],
        "ai_mode": "deterministic_only",
        "notice": "Sample assets were checked against approved workspace rules. No Ollama request or cloud AI provider was used.",
    }


@app.get("/api/dashboard", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    docs = db.scalars(select(ContentDocument).where(ContentDocument.workspace_id == user.workspace_id).order_by(desc(ContentDocument.updated_at))).all()
    all_findings = db.scalars(select(ReviewFinding).join(ContentDocument).where(ContentDocument.workspace_id == user.workspace_id)).all()
    open_findings = [f for f in all_findings if f.status == "open"]
    active_rules = db.scalar(select(func.count()).select_from(BrandRule).where(BrandRule.workspace_id == user.workspace_id, BrandRule.is_active.is_(True))) or 0
    score = int(round(sum(d.compliance_score for d in docs) / len(docs))) if docs else 100
    activities = db.scalars(select(AuditEvent).where(AuditEvent.workspace_id == user.workspace_id).order_by(desc(AuditEvent.created_at)).limit(8)).all()
    daily = Counter()
    today = datetime.now(timezone.utc).date()
    for event in db.scalars(select(AuditEvent).where(AuditEvent.workspace_id == user.workspace_id, AuditEvent.created_at >= datetime.now(timezone.utc) - timedelta(days=6))).all():
        daily[event.created_at.date().isoformat()] += 1
    weekly = [{"day": (today - timedelta(days=i)).strftime("%a"), "date": (today - timedelta(days=i)).isoformat(), "count": daily[(today - timedelta(days=i)).isoformat()]} for i in reversed(range(7))]
    return {
        "integrity_score": score,
        "total_documents": len(docs),
        "in_review": sum(1 for d in docs if d.status == "IN_REVIEW"),
        "publish_ready": sum(1 for d in docs if d.status == "PUBLISH_READY"),
        "open_findings": len(open_findings),
        "critical_findings": sum(1 for f in open_findings if f.severity == "critical"),
        "warning_findings": sum(1 for f in open_findings if f.severity == "warning"),
        "rule_count": active_rules,
        "recent_documents": [_document_out(doc, db) for doc in docs[:5]],
        "recent_activity": [{"id": a.id, "actor_name": a.actor_name, "action": a.action, "entity_type": a.entity_type,
           "entity_id": a.entity_id, "detail": a.detail, "created_at": a.created_at} for a in activities],
        "severity_counts": {"critical": sum(1 for f in open_findings if f.severity == "critical"),
                            "warning": sum(1 for f in open_findings if f.severity == "warning"),
                            "info": sum(1 for f in open_findings if f.severity == "info")},
        "weekly_activity": weekly,
    }


@app.post("/api/check-copy")
def check_copy(payload: CopyCheckRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Write-time copy check using approved deterministic rules plus local AI when installed.

    No cloud API key is required. Ollama is preferred for contextual checks; deterministic checks
    always run even if Ollama is not installed or available.
    """
    content = payload.text.strip()
    if not content:
        raise HTTPException(status_code=422, detail="Paste copy to check.")
    rules = db.scalars(select(BrandRule).where(
        BrandRule.workspace_id == user.workspace_id, BrandRule.is_active.is_(True)
    )).all()
    findings = inspect_content(content, [{"page": 1, "text": content, "spans": []}], rules, ai_candidates=rules)
    findings.extend(_fact_findings(content, user.workspace_id, db))
    rule_by_id = {rule.id: rule for rule in rules}
    output = []
    for item in findings:
        rule = rule_by_id.get(item.get("rule_id"))
        output.append({
            **item,
            "rule_code": rule.code if rule else None,
            "rule_title": rule.title if rule else "Unverifiable result",
            "source_document": rule.source_document if rule else None,
        })
    local_status = local_ai_status()
    local_failure = any(item.get("finding_type") == "unverifiable" and
                        str(item.get("flagged_text", "")).startswith("Local contextual verification could not complete")
                        for item in output)
    if local_status.get("model_available") and local_status.get("verification_enabled") and not local_failure:
        mode = "local_ai_plus_rules"
    elif local_status.get("model_available") and local_failure:
        mode = "local_ai_error_plus_rules"
    elif AI_VERIFICATION_ENABLED and ANTHROPIC_API_KEY:
        mode = "cloud_ai_plus_rules"
    else:
        mode = "deterministic"
    _audit(db, user, "copy.checked_at_write_time", "copy_check", str(uuid.uuid4()),
           {"characters": len(content), "finding_count": len(output), "mode": mode})
    db.commit()
    if mode == "local_ai_plus_rules":
        local_notice = f"Local contextual AI completed with {local_status.get('model')}. "
    elif mode == "local_ai_error_plus_rules":
        local_notice = "The local model was found but contextual inference failed; deterministic rules ran and contextual coverage is incomplete. Retry Ollama or review manually. "
    elif mode == "cloud_ai_plus_rules":
        local_notice = "Contextual review used the optional cloud provider already configured in this environment. Ollama is the no-key local alternative. "
    elif not local_status.get("verification_enabled"):
        local_notice = "Contextual AI verification is disabled; deterministic rule checks ran without an API key. Enable AI_VERIFICATION_ENABLED to allow the local model path. "
    else:
        local_notice = "No local AI model is currently available; deterministic rule checks ran without an API key. Install Ollama and pull the configured model to enable contextual checks. "
    return {"mode": mode, "characters_checked": len(content), "findings_count": len(output),
            "findings": output, "local_ai": local_status,
            "notice": local_notice + "Pricing freshness, claim evidence and logo treatment may require connected sources or human review; image contrast must be checked against the actual background."}


@app.get("/api/documents", response_model=list[DocumentOut])
def list_documents(q: str | None = None, status_filter: str | None = Query(default=None, alias="status"),
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = select(ContentDocument).where(ContentDocument.workspace_id == user.workspace_id).order_by(desc(ContentDocument.updated_at))
    if q:
        query = query.where(ContentDocument.filename.ilike(f"%{q[:100]}%"))
    if status_filter and status_filter != "all":
        query = query.where(ContentDocument.status == status_filter)
    return [_document_out(doc, db) for doc in db.scalars(query).all()]


@app.post("/api/documents/upload", response_model=DocumentOut, status_code=201)
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _consume_rate_limit(db, f"upload-user|{user.id}", UPLOAD_MAX_PER_USER, UPLOAD_WINDOW_MINUTES, "Upload limit reached for this account. Try again later.")
    scan_started = utcnow()
    filename = Path((file.filename or "upload").replace("\\", "/")).name[:255]
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Supported formats: PDF, DOCX, PPTX, TXT, MD, PNG, JPG, TIFF and BMP.")
    data = await read_upload_limited(file)
    try:
        detected_type = validate_upload_payload(filename, data)
        scan_result = clamav_scan(data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        pages, content = parse_document(filename, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Document parse failed")
        raise HTTPException(status_code=422, detail="Unable to parse this file. Confirm that it is a valid, unencrypted document.") from exc
    if len(pages) > 500:
        raise HTTPException(status_code=413, detail="Document exceeds the 500-page processing limit.")
    if len(content) > 2_000_000:
        raise HTTPException(status_code=413, detail="Extracted content exceeds the safe 2 MB text processing limit.")
    has_supported_visual_findings = any(page.get("missing_alt_text") for page in pages)
    if not content.strip() and not has_supported_visual_findings:
        raise HTTPException(status_code=422, detail="No readable text was found. For scanned PDFs, run OCR first or upload an OCR-readable version.")
    doc_id = str(uuid.uuid4())
    safe_disk_name = f"{doc_id}{suffix}"
    stored_path = store_bytes(data, safe_disk_name, detected_type)
    doc = ContentDocument(id=doc_id, workspace_id=user.workspace_id, filename=filename, stored_path=stored_path,
        file_data=data if STORE_UPLOADS_IN_DATABASE and not stored_path.startswith("s3://") else None,
        content_type=detected_type, content_text=content,
        pages_json=pages, page_count=len(pages), status="IN_REVIEW", compliance_score=100,
        size_bytes=len(data), sha256=sha256_hex(data), scan_status=scan_result["status"], created_by=user.id)
    db.add(doc); db.flush()
    rules = db.scalars(select(BrandRule).where(BrandRule.workspace_id == user.workspace_id, BrandRule.is_active.is_(True))).all()
    proposed = inspect_content(content, pages, rules, _retrieve_ai_candidates(db, content, rules, user.workspace_id))
    # PowerPoint image alt text is available in OOXML metadata; report verified missing descriptions.
    accessibility_rule = next((r for r in rules if r.code == "A11Y-001"), None)
    if accessibility_rule:
        for page in pages:
            for image_issue in page.get("missing_alt_text", []):
                proposed.append({
                    "rule_id": accessibility_rule.id, "severity": "warning", "finding_type": "accessibility",
                    "flagged_text": f'Image "{image_issue.get("name", "Picture")}" has no descriptive alternative text.',
                    "page_number": int(page.get("page", 1)),
                    "location_bbox": image_issue.get("location_bbox"),
                    "reasoning": "The PowerPoint image is missing a description in its alternative-text metadata. Decorative images can be marked decorative instead of given redundant text.",
                    "suggested_fix": accessibility_rule.suggested_fix,
                })
    proposed.extend(_fact_findings(content, user.workspace_id, db))
    scan = _persist_scan_findings(db, user, doc, rules, proposed, scan_started,
        "local_ai_plus_rules" if local_ai_status().get("model_available") and AI_VERIFICATION_ENABLED else "deterministic")
    db.flush(); _recompute_document(doc, db)
    _audit(db, user, "document.uploaded_and_scanned", "document", doc.id,
           {"filename": filename, "page_count": len(pages), "finding_count": len(proposed), "bytes": len(data), "scan_run_id": scan.id})
    record_snapshot(db, user.workspace_id)
    db.commit(); db.refresh(doc)
    return _document_out(doc, db)


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = _get_doc(doc_id, db, user)
    findings = db.scalars(select(ReviewFinding).options(joinedload(ReviewFinding.rule))
        .where(ReviewFinding.content_id == doc.id).order_by(desc(ReviewFinding.created_at))).all()
    return {"document": _document_out(doc, db), "content_text": doc.content_text,
            "pages": [{"page": p.get("page", i + 1), "text": p.get("text", ""), "note": p.get("note")}
                      for i, p in enumerate(doc.pages_json)],
            "findings": [_finding_out(f) for f in findings],
            "publish_ready": not any(f.status == "open" and f.severity == "critical" for f in findings),
            "ai_configured": bool(local_ai_status().get("model_available") or ANTHROPIC_API_KEY)}


@app.get("/api/documents/{doc_id}/preview/{page_number}")
def document_preview(doc_id: str, page_number: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = _get_doc(doc_id, db, user)
    if page_number < 1 or page_number > doc.page_count:
        raise HTTPException(status_code=404, detail="Page not found.")
    suffix = Path(doc.filename).suffix.lower()
    if suffix == ".pdf":
        try:
            pdf_bytes = read_stored_bytes(doc.stored_path, doc.file_data)
            pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
            page = pdf[page_number - 1]
            findings = db.scalars(select(ReviewFinding).where(ReviewFinding.content_id == doc.id,
                ReviewFinding.page_number == page_number, ReviewFinding.status == "open")).all()
            # Color coded rectangle overlays; source coordinates are PDF points.
            shape = page.new_shape()
            color_map = {"critical": (0.95, 0.26, 0.30), "warning": (1.0, 0.68, 0.20), "info": (0.25, 0.70, 0.98)}
            for finding in findings:
                bbox_info = finding.location_bbox or {}
                bbox = bbox_info.get("bbox")
                if not bbox or len(bbox) != 4:
                    continue
                try:
                    rect = fitz.Rect(*[float(v) for v in bbox])
                    if rect.is_empty or not rect.is_valid:
                        continue
                    color = color_map.get(finding.severity, (0.25, 0.70, 0.98))
                    rect.x0 -= 1.8; rect.y0 -= 1.8; rect.x1 += 1.8; rect.y1 += 1.8
                    shape.draw_rect(rect)
                    shape.finish(color=color, fill=None, width=1.8, closePath=True)
                except Exception:
                    continue
            shape.commit(overlay=True)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.35, 1.35), alpha=False)
            payload = pixmap.tobytes("png")
            pdf.close()
            return Response(content=payload, media_type="image/png", headers={"Cache-Control": "no-store"})
        except Exception as exc:
            logger.exception("PDF preview failed")
            raise HTTPException(status_code=500, detail="Could not render this PDF page.") from exc
    # Other formats are displayed as extracted text in the review UI, not as a fabricated image.
    raise HTTPException(status_code=415, detail="Image preview is supported for PDFs. Other document formats use the extracted text preview.")


@app.post("/api/documents/{doc_id}/rescan", response_model=DocumentOut)
def rescan_document(doc_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("Manager", "SME / Legal", "Brand Admin"))):
    doc = _get_doc(doc_id, db, user)
    if doc.status == "PUBLISH_READY":
        raise HTTPException(status_code=409, detail="Published documents cannot be rescanned in place. Upload a new version.")
    scan_started = utcnow()
    db.query(ReviewFinding).filter(ReviewFinding.content_id == doc.id).delete(synchronize_session=False)
    rules = db.scalars(select(BrandRule).where(BrandRule.workspace_id == user.workspace_id, BrandRule.is_active.is_(True))).all()
    proposed = inspect_content(doc.content_text, doc.pages_json, rules, _retrieve_ai_candidates(db, doc.content_text, rules, user.workspace_id))
    proposed.extend(_fact_findings(doc.content_text, user.workspace_id, db))
    scan = _persist_scan_findings(db, user, doc, rules, proposed, scan_started,
        "local_ai_plus_rules" if local_ai_status().get("model_available") and AI_VERIFICATION_ENABLED else "deterministic")
    db.flush(); _recompute_document(doc, db)
    _audit(db, user, "document.rescanned", "document", doc.id, {"rule_count": len(rules), "scan_run_id": scan.id})
    record_snapshot(db, user.workspace_id)
    db.commit(); db.refresh(doc)
    return _document_out(doc, db)


@app.delete("/api/documents/{doc_id}", status_code=204)
def delete_document(doc_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("Manager", "Brand Admin"))):
    doc = _get_doc(doc_id, db, user)
    stored_path = doc.stored_path
    _audit(db, user, "document.deleted", "document", doc.id, {"filename": doc.filename})
    db.delete(doc); db.flush()
    record_snapshot(db, user.workspace_id); db.commit()
    try:
        delete_stored_object(stored_path)
    except Exception:
        logger.exception("Could not remove stored upload %s", stored_path)
    return Response(status_code=204)


@app.post("/api/findings/{finding_id}/action", response_model=FindingActionResponse)
def finding_action(finding_id: str, payload: FindingAction, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    finding = db.scalar(select(ReviewFinding).options(joinedload(ReviewFinding.rule)).where(ReviewFinding.id == finding_id))
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found.")
    doc = _get_doc(finding.content_id, db, user)
    if doc.status == "PUBLISH_READY":
        raise HTTPException(status_code=409, detail="Published content is immutable in this workflow. Upload a new version to change it.")
    if finding.severity == "critical" and finding.finding_type in {"claim", "legal"} and user.role not in {"Manager", "SME / Legal", "Brand Admin"}:
        raise HTTPException(status_code=403, detail="Critical legal/claim findings require Manager, SME / Legal, or Brand Admin review.")
    if payload.status == "dismissed" and not (payload.note or "").strip():
        raise HTTPException(status_code=422, detail="A dismissal rationale is required for the audit trail.")
    if payload.status == "edited" and not (payload.applied_text or "").strip():
        raise HTTPException(status_code=422, detail="Enter the revised copy before marking this finding as fixed.")
    if payload.status in {"accepted", "edited", "dismissed"}:
        finding.status = payload.status
        finding.dismissal_reason = (payload.note or "").strip() if payload.status == "dismissed" else None
        if payload.status == "edited":
            finding.applied_text = (payload.applied_text or "").strip()[:10000]
    else:
        finding.status = "open"
        finding.dismissal_reason = None
    finding.updated_at = utcnow()
    _recompute_document(doc, db)
    _audit(db, user, f"finding.{payload.status}", "finding", finding.id,
           {"document_id": doc.id, "rule_code": finding.rule.code if finding.rule else None,
            "note": (payload.note or "")[:1000]})
    record_snapshot(db, user.workspace_id)
    db.commit(); db.refresh(finding)
    finding = db.scalar(select(ReviewFinding).options(joinedload(ReviewFinding.rule)).where(ReviewFinding.id == finding_id))
    open_critical = db.scalar(select(func.count()).select_from(ReviewFinding).where(
        ReviewFinding.content_id == doc.id, ReviewFinding.status == "open", ReviewFinding.severity == "critical")) or 0
    return {"finding": _finding_out(finding), "publish_ready": open_critical == 0}


@app.post("/api/documents/{doc_id}/publish")
def publish_document(doc_id: str, payload: PublishRequest, db: Session = Depends(get_db), user: User = Depends(require_roles("Manager", "SME / Legal", "Brand Admin"))):
    doc = _get_doc(doc_id, db, user)
    critical = db.scalars(select(ReviewFinding).where(ReviewFinding.content_id == doc.id,
        ReviewFinding.status == "open", ReviewFinding.severity == "critical")).all()
    if critical:
        raise HTTPException(status_code=409, detail=f"Publication blocked: {len(critical)} critical finding(s) remain open.")
    dismissed_critical = db.scalars(select(ReviewFinding).where(ReviewFinding.content_id == doc.id,
        ReviewFinding.status == "dismissed", ReviewFinding.severity == "critical")).all()
    if dismissed_critical and not (payload.override_note or "").strip():
        # Individual dismissal notes remain required, but final publication also needs an explicit sign-off note.
        raise HTTPException(status_code=422, detail="An override/sign-off note is required because one or more critical findings were dismissed.")
    previous = doc.status
    doc.status = "PUBLISH_READY"
    doc.updated_at = utcnow()
    _audit(db, user, "document.publish_ready", "document", doc.id,
        {"previous_status": previous, "override_note": (payload.override_note or "").strip(),
         "dismissed_critical_count": len(dismissed_critical)})
    notify(db, user.workspace_id, [doc.created_by] + workspace_admin_ids(db, user.workspace_id), "publish",
           f"{doc.filename} is Publish Ready", f"Approved by {user.name}.", "document", doc.id, user.id)
    record_snapshot(db, user.workspace_id)
    db.commit(); db.refresh(doc)
    return {"document": _document_out(doc, db), "message": "Document marked Publish Ready. This records governance approval; it does not publish the file to an external channel."}


@app.get("/api/documents/{doc_id}/export")
def export_document(doc_id: str, fmt: str = Query(default="json", pattern="^(json|csv)$"), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = _get_doc(doc_id, db, user)
    findings = db.scalars(select(ReviewFinding).options(joinedload(ReviewFinding.rule))
        .where(ReviewFinding.content_id == doc.id).order_by(ReviewFinding.created_at)).all()
    audit = db.scalars(select(AuditEvent).where(AuditEvent.entity_id == doc.id).order_by(AuditEvent.created_at)).all()
    exported = {"document": _document_out(doc, db), "findings": [_finding_out(f) for f in findings],
        "audit_events": [{"actor": a.actor_name, "action": a.action, "detail": a.detail, "created_at": a.created_at.isoformat()} for a in audit],
        "exported_at": utcnow().isoformat(), "note": "Governance report export. Suggested fixes are proposals; this export does not modify the original source file."}
    _audit(db, user, "document.exported", "document", doc.id, {"format": fmt})
    db.commit()
    if fmt == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=["finding_id", "rule_code", "severity", "category", "page", "status", "flagged_text", "reasoning", "suggested_fix", "applied_text", "dismissal_reason"])
        writer.writeheader()
        for f in findings:
            writer.writerow({"finding_id": f.id, "rule_code": f.rule.code if f.rule else "UNVERIFIABLE",
                "severity": f.severity, "category": f.finding_type, "page": f.page_number, "status": f.status,
                "flagged_text": f.flagged_text, "reasoning": f.reasoning, "suggested_fix": f.suggested_fix, "applied_text": f.applied_text or "",
                "dismissal_reason": f.dismissal_reason or ""})
        filename = f"contexa-{doc.id[:8]}-findings.csv"
        return Response(content=buffer.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})
    filename = f"contexa-{doc.id[:8]}-governance-report.json"
    return Response(content=json.dumps(exported, indent=2, default=str), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _extract_guideline_clauses(content: str, limit: int = 60) -> list[str]:
    """Create reviewable clause candidates from extracted source text; never auto-activate them."""
    clauses: list[str] = []
    for raw_line in content.splitlines():
        line = re.sub(r"^\s*(?:(?:[-*•–—]+)|(?:\d+[.)]))\s*", "", raw_line).strip()
        line = re.sub(r"\s+", " ", line)
        if not line:
            continue
        segments = [line] if len(line) <= 420 else re.split(r"(?<=[.!?])\s+", line)
        for segment in segments:
            clause = segment.strip(" \t-•")
            if len(clause) < 22:
                continue
            if len(clause) > 420:
                clause = clause[:417].rsplit(" ", 1)[0] + "…"
            if clause and clause.casefold() not in {old.casefold() for old in clauses}:
                clauses.append(clause)
            if len(clauses) >= limit:
                return clauses
    if not clauses and content.strip():
        for segment in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", content.strip())):
            if 22 <= len(segment) <= 420:
                clauses.append(segment)
            if len(clauses) >= limit:
                break
    return clauses


def _guideline_category(clause: str) -> str:
    value = clause.lower()
    if any(term in value for term in ("price", "pricing", "discount", "promotion", "offer", "rate card")):
        return "pricing"
    if any(term in value for term in ("claim", "substantiat", "evidence", "legal", "disclaimer", "guarantee")):
        return "claim"
    if any(term in value for term in ("tone", "voice", "respectful", "language", "audience")):
        return "tone"
    if any(term in value for term in ("product name", "terminology", "spelling", "capitalize", "naming")):
        return "terminology"
    if any(term in value for term in ("logo", "clearspace", "brand asset", "identity asset")):
        return "asset"
    if any(term in value for term in ("contrast", "colour", "color", "legibility", "wcag")):
        return "contrast"
    if any(term in value for term in ("alt text", "accessibility", "screen reader", "alternative text")):
        return "accessibility"
    return "guideline"


def _structure_aware_chunks(pages: list[dict[str, Any]], max_words: int = 300, overlap: int = 50) -> list[dict[str, Any]]:
    """Create page-preserving chunks with lightweight heading context."""
    result: list[dict[str, Any]] = []
    index = 0
    for page in pages:
        page_no = int(page.get("page", 1))
        current_heading = ""
        words: list[str] = []
        for raw_line in str(page.get("text", "")).splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip()
            if not line:
                continue
            is_heading = len(line) <= 100 and (line.isupper() or re.match(r"^(?:\d+(?:\.\d+)*[.)]?\s+|#{1,6}\s+)", line))
            if is_heading:
                current_heading = line.lstrip("# ")[:255]
            words.extend(line.split())
        if not words:
            continue
        step = max(1, max_words - overlap)
        for start in range(0, len(words), step):
            body = " ".join(words[start:start + max_words]).strip()
            if len(body) < 30:
                continue
            result.append({"page_number": page_no, "chunk_index": index, "heading": current_heading, "content": body})
            index += 1
            if start + max_words >= len(words):
                break
    return result


@app.post("/api/retrieval/search")
def search_guideline_knowledge(payload: dict[str, str], db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query_text = str(payload.get("query", "")).strip()[:2000]
    if len(query_text) < 2:
        raise HTTPException(status_code=422, detail="Enter at least two characters to search approved guideline knowledge.")
    query_vector, query_model = embed_with_model(query_text)
    candidate_ids: set[str] = set()
    lexical_ranks: dict[str, float] = {}
    if DATABASE_URL.startswith("postgresql"):
        # PostgreSQL full-text and pgvector indexes reduce the candidate set before reranking.
        try:
            lexical_rows = db.execute(text("""SELECT id, ts_rank_cd(to_tsvector('english', content), plainto_tsquery('english', :q)) AS rank
                FROM guideline_chunks WHERE workspace_id = :wid AND to_tsvector('english', content) @@ plainto_tsquery('english', :q)
                ORDER BY rank DESC LIMIT 50"""), {"q": query_text, "wid": user.workspace_id}).all()
            for row in lexical_rows:
                candidate_ids.add(str(row.id)); lexical_ranks[str(row.id)] = float(row.rank or 0)
            vector_literal = "[" + ",".join(f"{v:.8f}" for v in query_vector) + "]"
            vector_rows = db.execute(text("""SELECT id FROM guideline_chunks WHERE workspace_id = :wid
                AND embedding IS NOT NULL AND embedding_model = :model
                ORDER BY embedding <=> CAST(:qv AS vector) LIMIT 50"""),
                {"wid": user.workspace_id, "model": query_model, "qv": vector_literal}).all()
            candidate_ids.update(str(row.id) for row in vector_rows)
        except Exception:
            logger.exception("Indexed guideline retrieval failed; using workspace-scoped application fallback")
            candidate_ids.clear(); lexical_ranks.clear()
    if candidate_ids:
        chunks = db.scalars(select(GuidelineChunk).where(GuidelineChunk.workspace_id == user.workspace_id, GuidelineChunk.id.in_(candidate_ids))).all()
    else:
        # SQLite/demo fallback. The workspace filter is mandatory in both branches.
        chunks = db.scalars(select(GuidelineChunk).where(GuidelineChunk.workspace_id == user.workspace_id)).all()
    query_tokens = set(re.findall(r"[a-z0-9][a-z0-9_'-]*", query_text.lower()))
    ranked = []
    max_lexical = max(lexical_ranks.values(), default=0.0) or 1.0
    for chunk in chunks:
        terms = set(re.findall(r"[a-z0-9][a-z0-9_'-]*", chunk.content.lower()))
        overlap = len(query_tokens & terms) / max(1, len(query_tokens))
        pg_lexical = lexical_ranks.get(chunk.id, 0.0) / max_lexical
        lexical = max(overlap, pg_lexical)
        semantic = max(0.0, sum(a*b for a,b in zip(query_vector, chunk.embedding or []))) if chunk.embedding_model == query_model else 0.0
        score = 0.55 * lexical + 0.45 * semantic
        if lexical > 0 or semantic > 0.12:
            ranked.append((score, lexical, semantic, chunk))
    ranked.sort(key=lambda row: row[0], reverse=True)
    return {"query": query_text, "embedding_model": query_model, "retrieval_mode": "postgres-fulltext+pgvector" if DATABASE_URL.startswith("postgresql") else "offline-hybrid", "results": [
        {"id": chunk.id, "source_document": chunk.source_document, "source_sha256": chunk.source_sha256,
         "page_number": chunk.page_number, "heading": chunk.heading, "content": chunk.content,
         "score": round(score, 4), "lexical_score": round(lexical, 4), "semantic_score": round(semantic, 4),
         "embedding_model": chunk.embedding_model}
        for score, lexical, semantic, chunk in ranked[:10]]}


@app.post("/api/admin/rebuild-embeddings")
def rebuild_embeddings(db: Session = Depends(get_db), user: User = Depends(require_roles("Brand Admin"))):
    rules = db.scalars(select(BrandRule).where(BrandRule.workspace_id == user.workspace_id)).all()
    chunks = db.scalars(select(GuidelineChunk).where(GuidelineChunk.workspace_id == user.workspace_id)).all()
    for rule in rules:
        rule.embedding, rule.embedding_model = embed_with_model(f"{rule.title} {rule.category} {rule.rule_clause}")
    for chunk in chunks:
        chunk.embedding, chunk.embedding_model = embed_with_model(f"{chunk.heading} {chunk.content}")
    _audit(db, user, "knowledge.embeddings_rebuilt", "workspace", user.workspace_id,
        {"rules": len(rules), "chunks": len(chunks), "embedding_models": sorted({r.embedding_model for r in rules} | {c.embedding_model for c in chunks})})
    db.commit()
    actual_models = sorted({r.embedding_model for r in rules} | {c.embedding_model for c in chunks})
    return {"rules_rebuilt": len(rules), "chunks_rebuilt": len(chunks), "embedding_model": actual_models[0] if len(actual_models) == 1 else actual_models,
            "note": "If Ollama embeddings are enabled, every indexed row was rebuilt using the configured local embedding model."}


@app.post("/api/guidelines/import")
async def import_guideline(file: UploadFile = File(...), db: Session = Depends(get_db),
                           user: User = Depends(require_roles("Brand Admin"))):
    """Import policy content into paused rule candidates for a Brand Admin to review."""
    _consume_rate_limit(db, f"upload-user|{user.id}", UPLOAD_MAX_PER_USER, UPLOAD_WINDOW_MINUTES, "Upload limit reached for this account. Try again later.")
    filename = Path((file.filename or "guideline").replace("\\", "/")).name[:255]
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Supported guideline sources: PDF, DOCX, PPTX, TXT, Markdown or image OCR formats.")
    data = await read_upload_limited(file)
    try:
        validate_upload_payload(filename, data)
        clamav_scan(data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        pages, content = parse_document(filename, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Guideline import parse failed")
        raise HTTPException(status_code=422, detail="Unable to parse the guideline file. Confirm it is a valid, unencrypted document.") from exc
    if len(pages) > 500 or len(content) > 2_000_000:
        raise HTTPException(status_code=413, detail="Guidelines exceed the safe 500-page / 2 MB extracted-text processing limit.")
    if not content.strip():
        raise HTTPException(status_code=422, detail="No readable guideline text was extracted. Run OCR on scanned pages, then try again.")
    clauses = _extract_guideline_clauses(content)
    source_hash = hashlib.sha256(data).hexdigest()
    for chunk_data in _structure_aware_chunks(pages):
        chunk_vector, chunk_model = embed_with_model(f"{chunk_data['heading']} {chunk_data['content']}")
        db.add(GuidelineChunk(workspace_id=user.workspace_id, source_document=filename, source_sha256=source_hash,
            page_number=chunk_data["page_number"], chunk_index=chunk_data["chunk_index"], heading=chunk_data["heading"],
            content=chunk_data["content"], embedding=chunk_vector, embedding_model=chunk_model))
    if not clauses:
        raise HTTPException(status_code=422, detail="No distinct guideline clauses were extracted. Try a text-based PDF, DOCX, PPTX or TXT source.")
    created: list[BrandRule] = []
    for clause in clauses:
        category = _guideline_category(clause)
        severity = "critical" if category == "claim" and any(term in clause.lower() for term in ("legal", "disclaimer", "substantiat", "evidence", "guarantee")) else "warning"
        # Only derive a pattern for simple explicit prohibitions. Everything else stays review-first.
        pattern = None
        prohibition = re.search(r"(?:do not use|don't use|never use|avoid)\s+[\"'“‘]([^\"'”’]{3,60})[\"'”’]", clause, re.I)
        if not prohibition:
            prohibition = re.search(r"(?:do not use|don't use|never use|avoid)\s+([A-Za-z][A-Za-z0-9_-]{2,35}(?:\s+[A-Za-z][A-Za-z0-9_-]{1,20}){0,2})(?=\s+(?:in|on|for|within|when|unless|because)\b|[.,;:]|$)", clause, re.I)
        if prohibition:
            phrase = prohibition.group(1).strip()
            pattern = r"\b" + re.escape(phrase) + r"\b"
        code = f"IMP-{uuid.uuid4().hex[:8].upper()}"
        title_text = re.sub(r"\s+", " ", clause).strip()
        title = (title_text[:164].rsplit(" ", 1)[0] + "…") if len(title_text) > 165 else title_text
        rule_vector, rule_model = embed_with_model(f"{title} {category} {clause}")
        rule = BrandRule(workspace_id=user.workspace_id, code=code, title=title,
            category=category, rule_clause=clause, source_document=filename, pattern=pattern,
            severity=severity,
            suggested_fix="Review this extracted clause, confirm its meaning and add a deterministic pattern or enable grounded contextual review where appropriate.",
            embedding=rule_vector, embedding_model=rule_model, is_active=False)
        db.add(rule); created.append(rule)
    db.flush()
    skipped = max(0, len(content.splitlines()) - len(created))
    _audit(db, user, "guideline.imported_as_paused_candidates", "guideline_source", str(uuid.uuid4()),
           {"source_document": filename, "candidate_rules": len(created), "skipped_clauses": skipped})
    db.commit()
    return {"source_document": filename, "created_rules": len(created), "skipped_clauses": skipped,
            "rules": [{"id": r.id, "code": r.code, "title": r.title, "category": r.category,
                       "source_document": r.source_document, "is_active": r.is_active, "pattern_ready": bool(r.pattern)} for r in created],
            "note": "Imported clauses are PAUSED by default. Review each clause, correct titles, define deterministic patterns where applicable, and activate only after approval. The importer extracts candidates; it does not invent approved interpretations."}


def _asset_out(asset: BrandAsset) -> dict[str, Any]:
    return {"id": asset.id, "name": asset.name, "category": asset.category,
        "filename": asset.filename, "content_type": asset.content_type, "size_bytes": asset.size_bytes,
        "sha256": asset.sha256, "metadata": asset.metadata_json, "status": asset.status,
        "version_number": asset.version_number, "created_by": asset.created_by,
        "approved_by": asset.approved_by, "approved_at": asset.approved_at, "created_at": asset.created_at}


@app.get("/api/assets")
def list_brand_assets(category: str | None = None, status_filter: str | None = Query(default=None, alias="status"),
                     db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = select(BrandAsset).where(BrandAsset.workspace_id == user.workspace_id).order_by(desc(BrandAsset.created_at))
    if category:
        query = query.where(BrandAsset.category == category)
    if status_filter:
        query = query.where(BrandAsset.status == status_filter)
    return [_asset_out(item) for item in db.scalars(query.limit(300)).all()]


@app.post("/api/assets/upload", status_code=201)
async def upload_brand_asset(file: UploadFile = File(...), category: str = Query(default="logo"),
                             name: str | None = Query(default=None), db: Session = Depends(get_db),
                             user: User = Depends(require_roles("Brand Admin"))):
    _consume_rate_limit(db, f"upload-user|{user.id}", UPLOAD_MAX_PER_USER, UPLOAD_WINDOW_MINUTES, "Upload limit reached for this account. Try again later.")
    categories = {"logo", "font", "template", "color", "icon", "other"}
    if category not in categories:
        raise HTTPException(status_code=422, detail=f"Category must be one of: {', '.join(sorted(categories))}.")
    filename = Path((file.filename or "brand-asset").replace("\\", "/")).name[:255]
    suffix = Path(filename).suffix.lower()
    allowed = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".pdf", ".docx", ".pptx", ".ttf", ".otf", ".woff", ".woff2"}
    if suffix not in allowed:
        raise HTTPException(status_code=415, detail="Asset uploads support PNG/JPEG/WebP/TIFF/BMP, PDF, DOCX/PPTX and common font formats. SVG is intentionally excluded from inline serving for safety.")
    data = await read_upload_limited(file)
    try:
        detected_type = validate_upload_payload(filename, data)
        scanner = clamav_scan(data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    digest = sha256_hex(data)
    duplicate = db.scalar(select(BrandAsset).where(BrandAsset.workspace_id == user.workspace_id,
        BrandAsset.sha256 == digest).limit(1))
    if duplicate:
        raise HTTPException(status_code=409, detail=f"This exact asset already exists as {duplicate.name} (version {duplicate.version_number}).")
    display_name = (name or Path(filename).stem).strip()[:180] or Path(filename).stem
    latest_version = db.scalar(select(func.max(BrandAsset.version_number)).where(
        BrandAsset.workspace_id == user.workspace_id, BrandAsset.name == display_name)) or 0
    asset_id = str(uuid.uuid4())
    stored_path = store_bytes(data, f"asset-{asset_id}{suffix}", detected_type)
    file_data = data if STORE_UPLOADS_IN_DATABASE and not stored_path.startswith("s3://") else None
    asset = BrandAsset(id=asset_id, workspace_id=user.workspace_id, name=display_name, category=category,
        filename=filename, stored_path=stored_path, content_type=detected_type, size_bytes=len(data),
        sha256=digest, metadata_json={"scanner_status": scanner["status"]}, file_data=file_data,
        status="draft", version_number=latest_version + 1, created_by=user.id)
    db.add(asset); db.flush()
    _audit(db, user, "brand_asset.uploaded", "brand_asset", asset.id,
        {"name": asset.name, "category": category, "sha256": digest, "bytes": len(data), "scanner": scanner["status"]})
    db.commit(); db.refresh(asset)
    return _asset_out(asset)


@app.post("/api/assets/{asset_id}/approve")
def approve_brand_asset(asset_id: str, db: Session = Depends(get_db),
                        user: User = Depends(require_roles("Brand Admin", "SME / Legal"))):
    asset = db.get(BrandAsset, asset_id)
    if not asset or asset.workspace_id != user.workspace_id:
        raise HTTPException(status_code=404, detail="Brand asset not found.")
    if asset.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft assets can be approved.")
    asset.status = "approved"; asset.approved_by = user.id; asset.approved_at = utcnow()
    _audit(db, user, "brand_asset.approved", "brand_asset", asset.id,
        {"name": asset.name, "category": asset.category, "version": asset.version_number})
    db.commit(); db.refresh(asset)
    return _asset_out(asset)


@app.post("/api/assets/{asset_id}/archive")
def archive_brand_asset(asset_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("Brand Admin"))):
    asset = db.get(BrandAsset, asset_id)
    if not asset or asset.workspace_id != user.workspace_id:
        raise HTTPException(status_code=404, detail="Brand asset not found.")
    asset.status = "archived"
    _audit(db, user, "brand_asset.archived", "brand_asset", asset.id, {"name": asset.name})
    db.commit(); db.refresh(asset)
    return _asset_out(asset)


@app.get("/api/assets/{asset_id}/download")
def download_brand_asset(asset_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    asset = db.get(BrandAsset, asset_id)
    if not asset or asset.workspace_id != user.workspace_id or asset.status == "archived":
        raise HTTPException(status_code=404, detail="Brand asset not found.")
    try:
        payload = read_stored_bytes(asset.stored_path, asset.file_data)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Stored asset is unavailable.") from exc
    return Response(content=payload, media_type=asset.content_type,
        headers={"Content-Disposition": f'attachment; filename="{Path(asset.filename).name}"', "X-Content-Type-Options": "nosniff"})


@app.get("/api/rules", response_model=list[RuleOut])
def list_rules(q: str | None = None, active_only: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = select(BrandRule).where(BrandRule.workspace_id == user.workspace_id).order_by(BrandRule.code)
    if q:
        query = query.where((BrandRule.code.ilike(f"%{q[:80]}%")) | (BrandRule.title.ilike(f"%{q[:120]}%")) | (BrandRule.rule_clause.ilike(f"%{q[:120]}%")) | (BrandRule.source_document.ilike(f"%{q[:120]}%")))
    if active_only:
        query = query.where(BrandRule.is_active.is_(True))
    return db.scalars(query).all()


@app.get("/api/rules/{rule_id}/versions")
def list_rule_versions(rule_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rule = db.get(BrandRule, rule_id)
    if not rule or rule.workspace_id != user.workspace_id:
        raise HTTPException(status_code=404, detail="Rule not found.")
    versions = db.scalars(select(RuleVersion).where(
        RuleVersion.workspace_id == user.workspace_id,
        RuleVersion.rule_id == rule_id,
    ).order_by(RuleVersion.version_number.desc())).all()
    return [{"id": item.id, "rule_id": item.rule_id, "version_number": item.version_number,
             "snapshot": item.snapshot, "change_note": item.change_note,
             "created_by": item.created_by, "created_at": item.created_at}
            for item in versions]


@app.post("/api/rules", response_model=RuleOut, status_code=201)
def create_rule(payload: RuleCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("Brand Admin"))):
    if db.scalar(select(BrandRule).where(BrandRule.workspace_id == user.workspace_id, BrandRule.code == payload.code.upper())):
        raise HTTPException(status_code=409, detail="That rule code already exists in this workspace.")
    if payload.pattern:
        try: re.compile(payload.pattern)
        except re.error as exc: raise HTTPException(status_code=422, detail=f"Invalid regex pattern: {exc}") from exc
    data = payload.model_dump(); data["code"] = data["code"].upper()
    rule_vector, rule_model = embed_with_model(f"{payload.title} {payload.category} {payload.rule_clause}")
    rule = BrandRule(workspace_id=user.workspace_id, **data, embedding=rule_vector, embedding_model=rule_model)
    db.add(rule); db.flush()
    _record_rule_version(db, rule, user.id, "Initial rule version.")
    _audit(db, user, "rule.created", "rule", rule.id, {"code": rule.code})
    db.commit(); db.refresh(rule)
    return rule


@app.patch("/api/rules/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: str, payload: RuleUpdate, db: Session = Depends(get_db), user: User = Depends(require_roles("Brand Admin"))):
    rule = db.get(BrandRule, rule_id)
    if not rule or rule.workspace_id != user.workspace_id:
        raise HTTPException(status_code=404, detail="Rule not found.")
    data = payload.model_dump(exclude_unset=True)
    if "pattern" in data and data["pattern"]:
        try: re.compile(data["pattern"])
        except re.error as exc: raise HTTPException(status_code=422, detail=f"Invalid regex pattern: {exc}") from exc
    for key, value in data.items():
        setattr(rule, key, value)
    if {"title", "category", "rule_clause"} & data.keys():
        rule.embedding = embed(f"{rule.title} {rule.category} {rule.rule_clause}")
    rule.updated_at = utcnow()
    _record_rule_version(db, rule, user.id, "Updated fields: " + ", ".join(sorted(data.keys())))
    _audit(db, user, "rule.updated", "rule", rule.id, {"fields": sorted(data.keys()), "code": rule.code})
    db.commit(); db.refresh(rule)
    return rule


def _normalise_source_quote(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().casefold()


def _validate_fact_source(db: Session, user: User, source_document_id: str | None, source_quote: str) -> bool:
    if not source_document_id:
        return False
    source_doc = _get_doc(source_document_id, db, user)
    if _normalise_source_quote(source_quote) not in _normalise_source_quote(source_doc.content_text):
        raise HTTPException(status_code=422, detail="The supporting quotation was not found in the selected source document. Copy an exact passage or save the fact as a manual source attestation without linking a document.")
    return True


@app.get("/api/facts")
def list_facts(status_filter: str | None = Query(default=None, alias="status"),
              fact_type: str | None = None, q: str | None = None,
              db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = select(ApprovedFact).where(ApprovedFact.workspace_id == user.workspace_id).order_by(
        ApprovedFact.fact_key, ApprovedFact.version_number.desc())
    if status_filter:
        query = query.where(ApprovedFact.status == status_filter)
    if fact_type:
        query = query.where(ApprovedFact.fact_type == fact_type)
    if q:
        needle = f"%{q[:100]}%"
        query = query.where((ApprovedFact.fact_key.ilike(needle)) |
            (ApprovedFact.entity_name.ilike(needle)) | (ApprovedFact.canonical_value.ilike(needle)))
    return [_fact_out(fact) for fact in db.scalars(query.limit(500)).all()]


@app.post("/api/facts", status_code=201)
def create_fact(payload: FactCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("Brand Admin"))):
    fact_key = re.sub(r"[^a-z0-9_.-]+", "-", payload.fact_key.strip().lower()).strip("-")
    if len(fact_key) < 2:
        raise HTTPException(status_code=422, detail="Use a meaningful fact key.")
    if payload.valid_from and payload.valid_until and _aware(payload.valid_until) < _aware(payload.valid_from):
        raise HTTPException(status_code=422, detail="valid_until must be later than valid_from.")
    source_verified = _validate_fact_source(db, user, payload.source_document_id, payload.source_quote)
    version = (db.scalar(select(func.max(ApprovedFact.version_number)).where(
        ApprovedFact.workspace_id == user.workspace_id, ApprovedFact.fact_key == fact_key)) or 0) + 1
    fact = ApprovedFact(workspace_id=user.workspace_id, fact_key=fact_key,
        fact_type=payload.fact_type, entity_name=payload.entity_name.strip(),
        canonical_value=payload.canonical_value.strip(), currency=payload.currency,
        unit=payload.unit, aliases=[a.strip() for a in payload.aliases if a.strip()],
        source_document=payload.source_document.strip(), source_quote=payload.source_quote.strip(),
        source_document_id=payload.source_document_id, source_verified=source_verified, source_page=payload.source_page,
        valid_from=payload.valid_from, valid_until=payload.valid_until,
        status="draft", version_number=version, created_by=user.id)
    db.add(fact); db.flush()
    _audit(db, user, "fact.created", "approved_fact", fact.id,
        {"fact_key": fact_key, "version": version, "status": "draft"})
    db.commit(); db.refresh(fact)
    return _fact_out(fact)


@app.post("/api/facts/{fact_id}/approve")
def approve_fact(fact_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("Brand Admin", "SME / Legal"))):
    fact = db.get(ApprovedFact, fact_id)
    if not fact or fact.workspace_id != user.workspace_id:
        raise HTTPException(status_code=404, detail="Fact not found.")
    if fact.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft facts can be approved.")
    if len(fact.source_quote.strip()) < 8 or not fact.source_document.strip():
        raise HTTPException(status_code=422, detail="An approved fact requires a named source and supporting quotation.")
    now = utcnow()
    prior = db.scalars(select(ApprovedFact).where(ApprovedFact.workspace_id == user.workspace_id,
        ApprovedFact.fact_key == fact.fact_key, ApprovedFact.status == "approved")).all()
    for old in prior:
        old.status = "superseded"
        if old.valid_until is None:
            old.valid_until = now
    fact.status = "approved"
    fact.approved_by = user.id
    fact.approved_at = now
    if fact.valid_from is None:
        fact.valid_from = now
    _audit(db, user, "fact.approved", "approved_fact", fact.id,
        {"fact_key": fact.fact_key, "version": fact.version_number, "source_document": fact.source_document})
    db.commit(); db.refresh(fact)
    return _fact_out(fact)


@app.post("/api/facts/{fact_id}/revise", status_code=201)
def revise_fact(fact_id: str, payload: FactRevision, db: Session = Depends(get_db), user: User = Depends(require_roles("Brand Admin"))):
    old = db.get(ApprovedFact, fact_id)
    if not old or old.workspace_id != user.workspace_id:
        raise HTTPException(status_code=404, detail="Fact not found.")
    changes = payload.model_dump(exclude_unset=True)
    values = {key: getattr(old, key) for key in (
        "fact_key", "fact_type", "entity_name", "canonical_value", "currency", "unit", "aliases",
        "source_document", "source_quote", "source_document_id", "source_page", "valid_from", "valid_until")}
    values.update({key: value for key, value in changes.items() if value is not None})
    source_verified = _validate_fact_source(db, user, values.get("source_document_id"), values.get("source_quote", ""))
    version = (db.scalar(select(func.max(ApprovedFact.version_number)).where(
        ApprovedFact.workspace_id == user.workspace_id, ApprovedFact.fact_key == old.fact_key)) or old.version_number) + 1
    fact = ApprovedFact(workspace_id=user.workspace_id, **values, source_verified=source_verified, status="draft",
        version_number=version, supersedes_id=old.id, created_by=user.id)
    db.add(fact); db.flush()
    _audit(db, user, "fact.revision_created", "approved_fact", fact.id,
        {"fact_key": fact.fact_key, "version": version, "supersedes_id": old.id})
    db.commit(); db.refresh(fact)
    return _fact_out(fact)


@app.get("/api/findings/{finding_id}/evidence")
def finding_evidence(finding_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    finding = db.get(ReviewFinding, finding_id)
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found.")
    doc = _get_doc(finding.content_id, db, user)
    records = db.scalars(select(FindingEvidence).where(
        FindingEvidence.finding_id == finding.id, FindingEvidence.workspace_id == user.workspace_id)
        .order_by(FindingEvidence.created_at)).all()
    return {"finding_id": finding.id, "document_id": doc.id,
        "rule_version_id": finding.rule_version_id,
        "evidence": [{"id": e.id, "source_kind": e.source_kind, "source_id": e.source_id,
            "source_version": e.source_version, "source_label": e.source_label,
            "source_quote": e.source_quote, "content_quote": e.content_quote,
            "locator": e.locator, "verification_status": e.verification_status,
            "match_score": e.match_score, "created_at": e.created_at} for e in records]}


@app.get("/api/evidence-ledger")
def evidence_ledger(limit: int = Query(default=100, ge=1, le=500),
                    verification_status: str | None = None,
                    db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = select(FindingEvidence).where(FindingEvidence.workspace_id == user.workspace_id).order_by(desc(FindingEvidence.created_at))
    if verification_status:
        query = query.where(FindingEvidence.verification_status == verification_status)
    return [{"id": e.id, "finding_id": e.finding_id, "scan_run_id": e.scan_run_id,
        "source_kind": e.source_kind, "source_id": e.source_id, "source_version": e.source_version,
        "source_label": e.source_label, "source_quote": e.source_quote,
        "content_quote": e.content_quote, "locator": e.locator,
        "verification_status": e.verification_status, "match_score": e.match_score,
        "created_at": e.created_at} for e in db.scalars(query.limit(limit)).all()]


@app.get("/api/scans")
def list_scans(document_id: str | None = None, limit: int = Query(default=50, ge=1, le=200),
               db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = select(ScanRun).where(ScanRun.workspace_id == user.workspace_id).order_by(desc(ScanRun.started_at))
    if document_id:
        _get_doc(document_id, db, user)
        query = query.where(ScanRun.document_id == document_id)
    return [{"id": s.id, "document_id": s.document_id, "engine_mode": s.engine_mode,
        "ruleset_fingerprint": s.ruleset_fingerprint, "status": s.status,
        "total_findings": s.total_findings, "verified_evidence": s.verified_evidence,
        "unverifiable_evidence": s.unverifiable_evidence, "duration_ms": s.duration_ms,
        "metrics": s.metrics, "started_at": s.started_at, "completed_at": s.completed_at}
        for s in db.scalars(query.limit(limit)).all()]


@app.post("/api/policy-simulations")
def simulate_policy(payload: PolicySimulationRequest, db: Session = Depends(get_db), user: User = Depends(require_roles("Brand Admin"))):
    rule = db.get(BrandRule, payload.rule_id)
    if not rule or rule.workspace_id != user.workspace_id:
        raise HTTPException(status_code=404, detail="Rule not found.")
    try:
        proposed_regex = re.compile(payload.proposed_pattern, re.IGNORECASE | re.MULTILINE)
    except re.error as exc:
        raise HTTPException(status_code=422, detail=f"Invalid proposed pattern: {exc}") from exc
    documents = db.scalars(select(ContentDocument).where(ContentDocument.workspace_id == user.workspace_id)
        .order_by(desc(ContentDocument.updated_at)).limit(250)).all()
    affected = 0; matches_found = 0; sample: list[dict[str, Any]] = []
    for doc in documents:
        matches = list(proposed_regex.finditer(doc.content_text or ""))
        if not matches:
            continue
        affected += 1; matches_found += len(matches)
        for match in matches[:max(0, 10 - len(sample))]:
            start = max(0, match.start() - 90); end = min(len(doc.content_text), match.end() + 120)
            sample.append({"document_id": doc.id, "filename": doc.filename,
                "excerpt": " ".join(doc.content_text[start:end].split()), "matched_text": match.group(0)})
        if len(sample) >= 10:
            # Continue counting documents/matches, but do not retain unbounded excerpts.
            pass
    simulation = PolicySimulation(workspace_id=user.workspace_id, rule_id=rule.id,
        created_by=user.id, rule_code=rule.code, proposed_pattern=payload.proposed_pattern,
        documents_scanned=len(documents), documents_affected=affected, matches_found=matches_found,
        sample_matches=sample)
    db.add(simulation); db.flush()
    _audit(db, user, "policy.simulated", "policy_simulation", simulation.id,
        {"rule_code": rule.code, "documents_scanned": len(documents), "documents_affected": affected, "matches_found": matches_found})
    db.commit()
    return {"id": simulation.id, "rule_id": rule.id, "rule_code": rule.code,
        "documents_scanned": len(documents), "documents_affected": affected,
        "matches_found": matches_found, "sample_matches": sample,
        "notice": "Simulation only. The active rule has not been changed."}


@app.get("/api/policy-simulations")
def list_policy_simulations(limit: int = Query(default=50, ge=1, le=200),
                            db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(PolicySimulation).where(PolicySimulation.workspace_id == user.workspace_id)
        .order_by(desc(PolicySimulation.created_at)).limit(limit)).all()
    return [{"id": row.id, "rule_id": row.rule_id, "rule_code": row.rule_code,
        "proposed_pattern": row.proposed_pattern, "documents_scanned": row.documents_scanned,
        "documents_affected": row.documents_affected, "matches_found": row.matches_found,
        "sample_matches": row.sample_matches, "created_at": row.created_at} for row in rows]


@app.post("/api/policy-simulations/{simulation_id}/apply")
def apply_policy_simulation(simulation_id: str, payload: PolicyApplyRequest,
                            db: Session = Depends(get_db), user: User = Depends(require_roles("Brand Admin"))):
    simulation = db.get(PolicySimulation, simulation_id)
    if not simulation or simulation.workspace_id != user.workspace_id:
        raise HTTPException(status_code=404, detail="Simulation not found.")
    rule = db.get(BrandRule, simulation.rule_id) if simulation.rule_id else None
    if not rule or rule.workspace_id != user.workspace_id:
        raise HTTPException(status_code=409, detail="The original rule is no longer available. Create a new rule instead.")
    rule.pattern = simulation.proposed_pattern
    rule.updated_at = utcnow()
    rule.embedding = embed(f"{rule.title} {rule.category} {rule.rule_clause}")
    version = _record_rule_version(db, rule, user.id, payload.change_note)
    _audit(db, user, "policy.simulation_applied", "rule", rule.id,
        {"simulation_id": simulation.id, "version": version.version_number, "change_note": payload.change_note})
    db.commit(); db.refresh(rule)
    return {"rule_id": rule.id, "rule_code": rule.code, "version": version.version_number,
        "pattern": rule.pattern, "message": "The simulated pattern is now active as a new rule version."}


@app.get("/api/review-tasks")
def list_review_tasks(status_filter: str | None = Query(default=None, alias="status"),
                      db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = select(ReviewTask).where(ReviewTask.workspace_id == user.workspace_id).order_by(
        ReviewTask.priority.desc(), ReviewTask.created_at.desc())
    if status_filter:
        query = query.where(ReviewTask.status == status_filter)
    tasks = db.scalars(query.limit(300)).all()
    return [{"id": task.id, "document_id": task.document_id,
        "filename": db.get(ContentDocument, task.document_id).filename if db.get(ContentDocument, task.document_id) else "Deleted document",
        "assigned_role": task.assigned_role, "assigned_to": task.assigned_to,
        "reason": task.reason, "priority": task.priority, "status": task.status,
        "due_at": task.due_at, "created_at": task.created_at, "completed_at": task.completed_at} for task in tasks]


@app.patch("/api/review-tasks/{task_id}")
def update_review_task(task_id: str, payload: ReviewTaskUpdate,
                       db: Session = Depends(get_db), user: User = Depends(require_roles("Manager", "SME / Legal", "Brand Admin"))):
    task = db.get(ReviewTask, task_id)
    if not task or task.workspace_id != user.workspace_id:
        raise HTTPException(status_code=404, detail="Review task not found.")
    data = payload.model_dump(exclude_unset=True)
    if "assigned_to" in data and data["assigned_to"]:
        reviewer = db.get(User, data["assigned_to"])
        if not reviewer or reviewer.workspace_id != user.workspace_id or reviewer.role != task.assigned_role or not reviewer.is_active:
            raise HTTPException(status_code=422, detail="The assignee must be an active member of this workspace with the routed reviewer role.")
        task.assigned_to = reviewer.id
    if "status" in data and data["status"]:
        task.status = data["status"]
        task.completed_at = utcnow() if task.status == "completed" else None
    _audit(db, user, "review_task.updated", "review_task", task.id, data)
    db.commit()
    return {"id": task.id, "assigned_role": task.assigned_role, "assigned_to": task.assigned_to,
        "status": task.status, "completed_at": task.completed_at}


@app.post("/api/evaluation/seed")
def seed_evaluation_cases(db: Session = Depends(get_db), user: User = Depends(require_roles("Brand Admin"))):
    cases = []
    claim_samples = [
        "We are the #1 fastest platform for modern teams.",
        "Our service is guaranteed to increase revenue by 400%.",
        "The fastest way to save 35% on every campaign.",
        "Number one performance with unmatched results.",
        "Our product will never fail and is the best choice.",
        "Boost conversion by 28% with our guaranteed platform.",
    ]
    for index, content in enumerate(claim_samples, 1):
        expected = ["CLM-204", "LGL-002", "TERM-001"] if "unmatched" in content.lower() else ["CLM-204", "LGL-002"]
        cases.append((f"claim-{index:02d}", f"Absolute or quantified claim {index}", content, expected, "claim"))
    terminology_samples = [
        "Our revolutionary workflow saves teams time.",
        "This world-class platform supports every department.",
        "An unmatched experience for modern marketers.",
        "The game-changing campaign workspace is here.",
        "The product is unparalleled in its category.",
        "Contexa brings all brand work together.",
    ]
    for index, content in enumerate(terminology_samples, 1):
        expected = ["TERM-008"] if "Contexa" in content else (["TERM-001", "CLM-204", "LGL-002"] if any(word in content.lower() for word in ("unmatched", "unparalleled")) else ["TERM-001"])
        cases.append((f"terminology-{index:02d}", f"Terminology and naming case {index}", content, expected, "terminology"))
    tone_samples = [
        "Obviously, every team should use this product.",
        "This is a no-brainer for anyone who cares about growth.",
        "Everyone knows our solution is the right choice.",
        "Our workflow is idiot-proof and simple.",
        "Simply the best way to manage brand content.",
        "Obviously, this is a sensible option for most teams.",
    ]
    for index, content in enumerate(tone_samples, 1):
        expected = ["TONE-003"]
        if "Simply the best" in content:
            expected = ["TONE-003", "CLM-204", "LGL-002"]
        cases.append((f"tone-{index:02d}", f"Tone and language case {index}", content, expected, "tone"))
    pricing_samples = [
        "Subscribe today for ₹49,999/month.",
        "Get a 30% discount on the annual plan this week.",
        "Our offer is only $19 per month.",
        "Pricing starts at €29 for every team.",
        "Use promo code LAUNCH for 25% off.",
        "The campaign price is INR 12,500 until Friday.",
    ]
    for index, content in enumerate(pricing_samples, 1):
        expected = ["PRC-002", "CLM-204", "LGL-002"] if "save 30%" in content.lower() else ["PRC-002"]
        cases.append((f"pricing-{index:02d}", f"Pricing and promotion case {index}", content, expected, "pricing"))
    clean_samples = [
        "ContexA helps teams review content against approved brand guidance.",
        "Our workspace brings campaign files and reviewers together.",
        "Teams can organize product information in one place.",
        "Reviewers can compare drafts with current approved guidelines.",
        "The content team shared the updated launch calendar.",
        "Brand managers can review the document before publication.",
    ]
    for index, content in enumerate(clean_samples, 1):
        cases.append((f"clean-{index:02d}", f"Clean control copy {index}", content, [], "control"))
    additional_controls = [
        "The quarterly campaign calendar is ready for review.",
        "The product guide describes the available configuration options.",
        "Please contact the support team for assistance with setup.",
        "The marketing team shared the approved launch schedule.",
        "This page contains the current office contact information.",
        "The event registration window opens next Monday.",
        "Our team prepared a summary of the customer workshop.",
        "The document includes the project scope and delivery dates.",
        "The new dashboard groups files by campaign and owner.",
        "The support article explains how to update profile details.",
        "The design team submitted a revised layout for review.",
        "The meeting notes include the agreed action items.",
        "The onboarding checklist is available in the shared workspace.",
        "The product catalogue lists the available colour options.",
        "The newsletter draft is ready for editorial review.",
        "The team will publish the event agenda after approval.",
        "The latest brief describes the intended audience and channel.",
        "The content calendar includes the dates for each campaign.",
        "The help centre provides instructions for account access.",
        "The report summarizes feedback collected during the pilot.",
    ]
    for index, content in enumerate(additional_controls, 7):
        cases.append((f"control-extra-{index:02d}", f"Additional clean control {index}", content, [], "control"))
    created = 0
    for code, title, content, expected, category in cases:
        existing = db.scalar(select(EvaluationCase.id).where(
            EvaluationCase.workspace_id == user.workspace_id, EvaluationCase.case_code == code))
        if not existing:
            db.add(EvaluationCase(workspace_id=user.workspace_id, case_code=code,
                title=title, content_text=content, expected_rule_codes=expected, category=category))
            created += 1
    _audit(db, user, "evaluation.cases_seeded", "evaluation_suite", user.workspace_id, {"created": created})
    db.commit()
    return {"created": created, "total": db.scalar(select(func.count()).select_from(EvaluationCase).where(EvaluationCase.workspace_id == user.workspace_id)) or 0}


@app.post("/api/evaluation/import", status_code=201)
async def import_evaluation_cases(file: UploadFile = File(...), db: Session = Depends(get_db),
                                  user: User = Depends(require_roles("Brand Admin"))):
    """Import human-labelled evaluation cases from a CSV supplied by a Brand Admin.

    Required columns: case_code,title,content_text,expected_rule_codes,category.
    Separate multiple rule codes using a pipe, for example CLM-204|TERM-001.
    Existing case_code rows are updated so a labelled suite can be corrected over time.
    """
    _consume_rate_limit(db, f"upload-user|{user.id}", UPLOAD_MAX_PER_USER, UPLOAD_WINDOW_MINUTES,
                        "Upload limit reached for this account. Try again later.")
    filename = Path((file.filename or "evaluation.csv").replace("\\", "/")).name[:255]
    if Path(filename).suffix.lower() != ".csv":
        raise HTTPException(status_code=415, detail="Evaluation labels must be uploaded as a UTF-8 CSV file.")
    raw = await read_upload_limited(file)
    if not raw or b"\x00" in raw:
        raise HTTPException(status_code=422, detail="The evaluation CSV is empty or contains binary data.")
    clamav_scan(raw)
    try:
        decoded = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="Evaluation CSV must use UTF-8 encoding.") from exc
    reader = csv.DictReader(io.StringIO(decoded))
    required = {"case_code", "title", "content_text", "expected_rule_codes", "category"}
    if not reader.fieldnames or not required.issubset({str(x).strip() for x in reader.fieldnames if x}):
        raise HTTPException(status_code=422, detail="CSV headers must include: case_code,title,content_text,expected_rule_codes,category.")
    valid_codes = set(db.scalars(select(BrandRule.code).where(BrandRule.workspace_id == user.workspace_id)).all())
    created = updated = 0
    seen: set[str] = set()
    for row_number, row in enumerate(reader, start=2):
        if row_number > 502:
            raise HTTPException(status_code=413, detail="Import is limited to 500 evaluation cases per file.")
        case_code = str(row.get("case_code") or "").strip()[:60]
        title = str(row.get("title") or "").strip()[:180]
        content = str(row.get("content_text") or "").strip()
        category = str(row.get("category") or "general").strip()[:50] or "general"
        if not re.fullmatch(r"[A-Za-z0-9._-]{2,60}", case_code) or not title or not content:
            raise HTTPException(status_code=422, detail=f"Row {row_number}: case_code, title and content_text are required; case_code may contain letters, numbers, dot, underscore and dash.")
        if len(content) > 100_000:
            raise HTTPException(status_code=422, detail=f"Row {row_number}: content_text exceeds 100,000 characters.")
        if case_code in seen:
            raise HTTPException(status_code=422, detail=f"Row {row_number}: duplicate case_code {case_code} in this CSV.")
        seen.add(case_code)
        expected = sorted({part.strip() for part in re.split(r"[|;]", str(row.get("expected_rule_codes") or "")) if part.strip()})
        unknown = sorted(set(expected) - valid_codes)
        if unknown:
            raise HTTPException(status_code=422, detail=f"Row {row_number}: unknown rule codes: {', '.join(unknown)}.")
        case = db.scalar(select(EvaluationCase).where(EvaluationCase.workspace_id == user.workspace_id,
            EvaluationCase.case_code == case_code))
        if case:
            case.title = title; case.content_text = content; case.expected_rule_codes = expected; case.category = category; case.is_active = True
            updated += 1
        else:
            db.add(EvaluationCase(workspace_id=user.workspace_id, case_code=case_code, title=title,
                content_text=content, expected_rule_codes=expected, category=category, is_active=True))
            created += 1
    if created + updated == 0:
        raise HTTPException(status_code=422, detail="The CSV contains no evaluation rows.")
    _audit(db, user, "evaluation.labels_imported", "evaluation_suite", user.workspace_id,
        {"filename": filename, "created": created, "updated": updated, "total_rows": created + updated})
    db.commit()
    return {"created": created, "updated": updated, "total": db.scalar(select(func.count()).select_from(EvaluationCase).where(
        EvaluationCase.workspace_id == user.workspace_id, EvaluationCase.is_active.is_(True))) or 0,
        "note": "Imported expected findings are human-supplied labels. Review and document label provenance before reporting benchmark quality."}


@app.post("/api/evaluation/run")
def run_evaluation(db: Session = Depends(get_db), user: User = Depends(require_roles("Brand Admin", "Manager"))):
    rules = db.scalars(select(BrandRule).where(BrandRule.workspace_id == user.workspace_id, BrandRule.is_active.is_(True))).all()
    cases = db.scalars(select(EvaluationCase).where(EvaluationCase.workspace_id == user.workspace_id,
        EvaluationCase.is_active.is_(True)).order_by(EvaluationCase.case_code)).all()
    if not cases:
        raise HTTPException(status_code=409, detail="No evaluation cases exist. Seed the benchmark suite first.")
    tp = fp = fn = 0; details = []
    for case in cases:
        predictions = inspect_content(case.content_text, [{"page": 1, "text": case.content_text, "spans": []}], rules, ai_candidates=[])
        by_id = {r.id: r.code for r in rules}
        predicted = {by_id[item.get("rule_id")] for item in predictions if item.get("rule_id") in by_id}
        expected = set(case.expected_rule_codes or [])
        case_tp = len(expected & predicted); case_fp = len(predicted - expected); case_fn = len(expected - predicted)
        tp += case_tp; fp += case_fp; fn += case_fn
        details.append({"case_code": case.case_code, "title": case.title,
            "expected": sorted(expected), "predicted": sorted(predicted),
            "true_positives": case_tp, "false_positives": case_fp, "false_negatives": case_fn,
            "passed": case_fp == 0 and case_fn == 0})
    precision = tp / (tp + fp) if tp + fp else (1.0 if fn == 0 else 0.0)
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
    run = EvaluationRun(workspace_id=user.workspace_id, initiated_by=user.id, case_count=len(cases),
        true_positives=tp, false_positives=fp, false_negatives=fn,
        precision=round(precision, 4), recall=round(recall, 4), f1_score=round(f1, 4), details=details)
    db.add(run); db.flush()
    _audit(db, user, "evaluation.completed", "evaluation_run", run.id,
        {"case_count": len(cases), "precision": run.precision, "recall": run.recall, "f1": run.f1_score})
    db.commit()
    return {"id": run.id, "case_count": run.case_count, "true_positives": tp,
        "false_positives": fp, "false_negatives": fn, "precision": run.precision,
        "recall": run.recall, "f1_score": run.f1_score, "details": details,
        "note": "Deterministic rule-engine benchmark. It does not measure contextual AI quality."}


@app.get("/api/evaluation/runs")
def evaluation_runs(limit: int = Query(default=20, ge=1, le=100),
                    db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    runs = db.scalars(select(EvaluationRun).where(EvaluationRun.workspace_id == user.workspace_id)
        .order_by(desc(EvaluationRun.created_at)).limit(limit)).all()
    return [{"id": r.id, "case_count": r.case_count, "true_positives": r.true_positives,
        "false_positives": r.false_positives, "false_negatives": r.false_negatives,
        "precision": r.precision, "recall": r.recall, "f1_score": r.f1_score,
        "created_at": r.created_at} for r in runs]


@app.get("/api/brand-intelligence")
def brand_intelligence(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    facts = db.scalars(select(ApprovedFact).where(ApprovedFact.workspace_id == user.workspace_id)).all()
    now = datetime.now(timezone.utc)
    approved = [f for f in facts if f.status == "approved"]
    stale = [f for f in approved if _aware(f.valid_until) is not None and _aware(f.valid_until) < now]
    findings = db.scalars(select(ReviewFinding).join(ContentDocument).where(
        ContentDocument.workspace_id == user.workspace_id)).all()
    rule_counts = Counter(f.rule.code for f in findings if f.rule)
    evidence = db.scalars(select(FindingEvidence).where(FindingEvidence.workspace_id == user.workspace_id)).all()
    verified = sum(1 for e in evidence if e.verification_status in {"grounded", "linked"})
    latest_eval = db.scalar(select(EvaluationRun).where(EvaluationRun.workspace_id == user.workspace_id)
        .order_by(desc(EvaluationRun.created_at)).limit(1))
    open_tasks = db.scalar(select(func.count()).select_from(ReviewTask).where(
        ReviewTask.workspace_id == user.workspace_id, ReviewTask.status != "completed")) or 0
    assets = db.scalars(select(BrandAsset).where(BrandAsset.workspace_id == user.workspace_id)).all()
    return {"assets": {"total": len(assets), "approved": sum(1 for a in assets if a.status == "approved"),
            "draft": sum(1 for a in assets if a.status == "draft"), "archived": sum(1 for a in assets if a.status == "archived"),
            "categories": dict(Counter(a.category for a in assets))},
        "facts": {"total": len(facts), "approved": len(approved), "draft": sum(1 for f in facts if f.status == "draft"),
            "expired_or_stale": len(stale)},
        "evidence": {"total": len(evidence), "grounded_or_linked": verified,
            "unverifiable": sum(1 for e in evidence if e.verification_status == "unverifiable"),
            "grounding_rate": round(verified / len(evidence) * 100, 1) if evidence else None},
        "findings": {"total": len(findings), "open": sum(1 for f in findings if f.status == "open"),
            "dismissed": sum(1 for f in findings if f.status == "dismissed"),
            "top_rules": [{"rule_code": code, "count": count} for code, count in rule_counts.most_common(8)]},
        "review_tasks": {"open": open_tasks},
        "latest_evaluation": ({"id": latest_eval.id, "precision": latest_eval.precision,
            "recall": latest_eval.recall, "f1_score": latest_eval.f1_score,
            "case_count": latest_eval.case_count, "created_at": latest_eval.created_at} if latest_eval else None),
        "generated_at": utcnow()}


@app.get("/api/insights", response_model=InsightOut)
def insights(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rules = db.scalars(select(BrandRule).where(BrandRule.workspace_id == user.workspace_id).order_by(BrandRule.code)).all()
    findings = db.scalars(select(ReviewFinding).join(ContentDocument).where(ContentDocument.workspace_id == user.workspace_id)).all()
    rule_rows: list[dict[str, Any]] = []
    for rule in rules:
        matches = [f for f in findings if f.rule_id == rule.id]
        dismissed = sum(1 for f in matches if f.status == "dismissed")
        total = len(matches)
        gci = max(0, min(100, round(100 - dismissed / total * 100))) if total else 100
        rule_rows.append({"id": rule.id, "code": rule.code, "title": rule.title, "category": rule.category,
            "triggered": total, "dismissed": dismissed, "gci": gci,
            "status": "Candidate for clarification" if total > 0 and gci < 60 else "Healthy" if total else "No data"})
    by_category = Counter(f.finding_type for f in findings)
    dismissed_total = sum(1 for f in findings if f.status == "dismissed")
    total_findings = len(findings)
    overall_gci = max(0, min(100, round(100 - dismissed_total / total_findings * 100))) if total_findings else 100
    return {"rule_clarity_index": overall_gci, "total_findings": total_findings, "dismissed_findings": dismissed_total,
            "rules": rule_rows, "findings_by_category": dict(by_category)}


@app.get("/api/audit/verify")
def verify_audit_chain(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    events = db.scalars(select(AuditEvent).where(AuditEvent.workspace_id == user.workspace_id)
        .order_by(AuditEvent.created_at, AuditEvent.id)).all()
    legacy = [event for event in events if not event.event_hash]
    chained = [event for event in events if event.event_hash]
    # Older rows created before hash chaining are counted as a legacy prefix. The
    # first chained record anchors to the most recent legacy row; later links are verified.
    anchor = _audit_hash(legacy[-1], "0" * 64) if legacy else "0" * 64
    expected_previous = anchor
    checked = 0
    first_invalid = None
    for index, event in enumerate(chained):
        expected_hash = _audit_hash(event, event.previous_hash or "0" * 64)
        if event.event_hash != expected_hash or (index > 0 and event.previous_hash != expected_previous) or (index == 0 and event.previous_hash != anchor):
            first_invalid = event.id
            break
        expected_previous = event.event_hash
        checked += 1
    return {"valid": first_invalid is None, "events_total": len(events), "events_verified": checked,
        "legacy_events_unhashed": len(legacy), "first_invalid_event_id": first_invalid,
        "integrity_model": "workspace-scoped SHA-256 hash chain; tamper-evident after chain activation, not an external immutable ledger"}


@app.get("/api/audit")
def audit_log(limit: int = Query(default=100, ge=1, le=500), entity_type: str | None = None,
              db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = select(AuditEvent).where(AuditEvent.workspace_id == user.workspace_id).order_by(desc(AuditEvent.created_at))
    if entity_type:
        query = query.where(AuditEvent.entity_type == entity_type)
    events = db.scalars(query.limit(limit)).all()
    return [{"id": a.id, "actor_id": a.actor_id, "actor_name": a.actor_name, "action": a.action,
             "entity_type": a.entity_type, "entity_id": a.entity_id, "detail": a.detail,
             "previous_hash": a.previous_hash, "event_hash": a.event_hash, "created_at": a.created_at} for a in events]




def _export_value(value: Any) -> Any:
    """Convert ORM scalar payloads to JSON-safe values without exposing secrets."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bytes):
        return None
    if isinstance(value, dict):
        return {str(k): _export_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_export_value(v) for v in value]
    return value


def _row_export(row: Any, exclude: set[str] | None = None) -> dict[str, Any]:
    excluded = exclude or set()
    return {column.name: _export_value(getattr(row, column.name))
            for column in row.__table__.columns if column.name not in excluded}


@app.get("/api/workspace/export")
def export_workspace(db: Session = Depends(get_db), user: User = Depends(require_roles("Brand Admin"))):
    """Download a workspace export with JSON metadata and original uploaded files."""
    workspace_id = user.workspace_id
    _audit(db, user, "workspace.exported", "workspace", workspace_id, {"format": "zip"})
    db.commit()
    docs = db.scalars(select(ContentDocument).where(ContentDocument.workspace_id == workspace_id)).all()
    assets = db.scalars(select(BrandAsset).where(BrandAsset.workspace_id == workspace_id)).all()
    rules = db.scalars(select(BrandRule).where(BrandRule.workspace_id == workspace_id)).all()
    findings = db.scalars(select(ReviewFinding).join(ContentDocument).where(ContentDocument.workspace_id == workspace_id)).all()
    collections = {
        "users": [_row_export(x, {"password_hash"}) for x in db.scalars(select(User).where(User.workspace_id == workspace_id)).all()],
        "brand_rules": [_row_export(x, {"embedding"}) for x in rules],
        "rule_versions": [_row_export(x) for x in db.scalars(select(RuleVersion).where(RuleVersion.workspace_id == workspace_id)).all()],
        "approved_facts": [_row_export(x) for x in db.scalars(select(ApprovedFact).where(ApprovedFact.workspace_id == workspace_id)).all()],
        "documents": [_row_export(x, {"file_data", "stored_path"}) for x in docs],
        "findings": [_row_export(x) for x in findings],
        "finding_evidence": [_row_export(x) for x in db.scalars(select(FindingEvidence).where(FindingEvidence.workspace_id == workspace_id)).all()],
        "scan_runs": [_row_export(x) for x in db.scalars(select(ScanRun).where(ScanRun.workspace_id == workspace_id)).all()],
        "policy_simulations": [_row_export(x) for x in db.scalars(select(PolicySimulation).where(PolicySimulation.workspace_id == workspace_id)).all()],
        "evaluation_cases": [_row_export(x) for x in db.scalars(select(EvaluationCase).where(EvaluationCase.workspace_id == workspace_id)).all()],
        "evaluation_runs": [_row_export(x) for x in db.scalars(select(EvaluationRun).where(EvaluationRun.workspace_id == workspace_id)).all()],
        "review_tasks": [_row_export(x) for x in db.scalars(select(ReviewTask).where(ReviewTask.workspace_id == workspace_id)).all()],
        "guideline_chunks": [_row_export(x, {"embedding"}) for x in db.scalars(select(GuidelineChunk).where(GuidelineChunk.workspace_id == workspace_id)).all()],
        "brand_assets": [_row_export(x, {"file_data", "stored_path"}) for x in assets],
        "audit_events": [_row_export(x) for x in db.scalars(select(AuditEvent).where(AuditEvent.workspace_id == workspace_id).order_by(AuditEvent.created_at)).all()],
    }
    total_bytes = sum(int(x.size_bytes or 0) for x in docs) + sum(int(x.size_bytes or 0) for x in assets)
    if total_bytes > 200 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Workspace export exceeds the 200 MB archive limit. Export documents individually or configure a larger export worker.")
    archive = io.BytesIO()
    missing_files: list[dict[str, str]] = []
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("manifest.json", json.dumps({"workspace": {"id": workspace_id, "name": user.workspace_name},
            "exported_at": utcnow().isoformat(), "format_version": 1, "collections": collections,
            "files": {"documents": len(docs), "assets": len(assets)}}, ensure_ascii=False, indent=2))
        for doc in docs:
            try:
                raw = read_stored_bytes(doc.stored_path, doc.file_data)
                safe_name = Path(doc.filename).name.replace("/", "_").replace("\\", "_")
                zf.writestr(f"files/documents/{doc.id}/{safe_name}", raw)
            except Exception as exc:
                logger.warning("Workspace export could not read document %s: %s", doc.id, exc)
                missing_files.append({"id": doc.id, "name": doc.filename, "kind": "document"})
        for asset in assets:
            try:
                raw = read_stored_bytes(asset.stored_path, asset.file_data)
                safe_name = Path(asset.filename).name.replace("/", "_").replace("\\", "_")
                zf.writestr(f"files/assets/{asset.id}/{safe_name}", raw)
            except Exception as exc:
                logger.warning("Workspace export could not read asset %s: %s", asset.id, exc)
                missing_files.append({"id": asset.id, "name": asset.filename, "kind": "asset"})
        if missing_files:
            zf.writestr("missing_files.json", json.dumps(missing_files, indent=2))
    archive.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="contexa-workspace-{workspace_id[:12]}-export.zip"'}
    return StreamingResponse(archive, media_type="application/zip", headers=headers)


@app.delete("/api/workspace", status_code=204)
def delete_workspace(payload: WorkspaceDeleteRequest, db: Session = Depends(get_db), user: User = Depends(require_roles("Brand Admin"))):
    """Irreversibly delete the current workspace after password + exact-name confirmation."""
    if payload.workspace_name_confirmation.strip() != user.workspace_name:
        raise HTTPException(status_code=400, detail="Workspace name confirmation does not match.")
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=403, detail="Password confirmation failed.")
    workspace_id = user.workspace_id
    docs = db.scalars(select(ContentDocument).where(ContentDocument.workspace_id == workspace_id)).all()
    assets = db.scalars(select(BrandAsset).where(BrandAsset.workspace_id == workspace_id)).all()
    stored_paths = [x.stored_path for x in docs] + [x.stored_path for x in assets]
    doc_ids = [x.id for x in docs]
    rule_ids = [x.id for x in db.scalars(select(BrandRule).where(BrandRule.workspace_id == workspace_id)).all()]
    # Delete dependent rows explicitly; this works consistently with SQLite and PostgreSQL.
    db.query(FindingEvidence).filter(FindingEvidence.workspace_id == workspace_id).delete(synchronize_session=False)
    # Trust OS extension records are removed explicitly so deletion works on both SQLite
    # and PostgreSQL even when deployments do not rely on database-level cascades.
    db.query(RegulatoryAssessment).filter(RegulatoryAssessment.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(BrandIncident).filter(BrandIncident.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(RegulatoryRequirement).filter(RegulatoryRequirement.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(LanguageReview).filter(LanguageReview.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(DigitalTwinScenario).filter(DigitalTwinScenario.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(AgentRun).filter(AgentRun.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(MediaInspection).filter(MediaInspection.workspace_id == workspace_id).delete(synchronize_session=False)
    workspace_passport_ids = [row[0] for row in db.query(TrustPassport.public_id).filter(TrustPassport.workspace_id == workspace_id).all()]
    if workspace_passport_ids:
        db.query(PublicPassportIndex).filter(PublicPassportIndex.public_id.in_(workspace_passport_ids)).delete(synchronize_session=False)
    db.query(TrustPassport).filter(TrustPassport.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(TruthDriftEvent).filter(TruthDriftEvent.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(MonitoredSource).filter(MonitoredSource.workspace_id == workspace_id).delete(synchronize_session=False)
    if doc_ids:
        db.query(ReviewFinding).filter(ReviewFinding.content_id.in_(doc_ids)).delete(synchronize_session=False)
        db.query(ReviewTask).filter(ReviewTask.document_id.in_(doc_ids)).delete(synchronize_session=False)
    db.query(ScanRun).filter(ScanRun.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(PolicySimulation).filter(PolicySimulation.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(EvaluationRun).filter(EvaluationRun.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(EvaluationCase).filter(EvaluationCase.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(ApprovedFact).filter(ApprovedFact.workspace_id == workspace_id).update({ApprovedFact.supersedes_id: None}, synchronize_session=False)
    db.query(ApprovedFact).filter(ApprovedFact.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(RuleVersion).filter(RuleVersion.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(GuidelineChunk).filter(GuidelineChunk.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(BrandAsset).filter(BrandAsset.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(ContentDocument).filter(ContentDocument.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(BrandRule).filter(BrandRule.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(AuthActionToken).filter(AuthActionToken.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(AuditEvent).filter(AuditEvent.workspace_id == workspace_id).delete(synchronize_session=False)
    db.query(User).filter(User.workspace_id == workspace_id).delete(synchronize_session=False)
    db.commit()
    for stored_path in stored_paths:
        try:
            delete_stored_object(stored_path)
        except Exception:
            logger.exception("Workspace deletion could not remove stored object %s", stored_path)
    return Response(status_code=204)


@app.get("/api/settings")
def settings(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    local_status = local_ai_status()
    local_ready = bool(local_status.get("model_available"))
    return {"workspace": {"id": user.workspace_id, "name": user.workspace_name, "environment": APP_ENV},
            "backend": {"database": "postgresql + pgvector" if DATABASE_URL.startswith("postgresql") else "SQLite (local development)",
                        "upload_limit_mb": MAX_UPLOAD_MB, "object_storage": "s3-compatible" if os.getenv("S3_BUCKET") else ("database" if STORE_UPLOADS_IN_DATABASE else "private-local"),
                        "email_verification_required": EMAIL_VERIFICATION_REQUIRED,
                        "argon2_password_hashing": __import__("app.security", fromlist=["_ARGON2"])._ARGON2 is not None,
                        "ai_configured": local_ready or bool(ANTHROPIC_API_KEY),
                        "ai_model": OLLAMA_MODEL if local_ready else (ANTHROPIC_MODEL if ANTHROPIC_API_KEY else None),
                        "ai_provider": "Ollama local" if local_ready else ("Claude via Cloudflare AI Gateway" if ANTHROPIC_API_KEY and ANTHROPIC_BASE_URL and "gateway.ai.cloudflare.com" in ANTHROPIC_BASE_URL else ("Claude API" if ANTHROPIC_API_KEY else "Deterministic rules only")),
                        "local_ai": local_status,
                        "embeddings": {"provider": embedding_model_label(), "ollama_enabled": OLLAMA_EMBEDDINGS_ENABLED, "model": OLLAMA_EMBEDDING_MODEL if OLLAMA_EMBEDDINGS_ENABLED else None},
                        "ai_note": "No API key is required. Install Ollama and pull the configured model for local contextual verification. Deterministic checks always work without local AI."},
            "cloudflare": {"edge_gateway_enabled": CLOUDFLARE_EDGE_ENABLED,
                           "origin_auth_enabled": bool(CLOUDFLARE_EDGE_ENABLED and CLOUDFLARE_ORIGIN_SHARED_SECRET),
                           "api_url": PUBLIC_API_URL or None,
                           "turnstile_enabled": bool(TURNSTILE_SECRET_KEY),
                           "r2_enabled": bool(S3_BUCKET and "r2.cloudflarestorage.com" in os.getenv("S3_ENDPOINT_URL", "")),
                           "ai_gateway_enabled": bool(ANTHROPIC_BASE_URL and "gateway.ai.cloudflare.com" in ANTHROPIC_BASE_URL)},
            "trust_os": {"enabled": True,
                         "modules": ["truth_drift", "trust_passports", "multimodal", "governance_agents", "digital_twin", "indic_intelligence", "regulatory_screening", "incident_management"],
                         "scheduled_monitoring_configured": bool(TRUTH_DRIFT_CRON_TOKEN),
                         "passport_signing_key_configured": bool(os.getenv("TRUST_PASSPORT_SIGNING_KEY")) and len(TRUST_PASSPORT_SIGNING_KEY) >= 32 and "replace-with" not in TRUST_PASSPORT_SIGNING_KEY.lower(),
                         "passport_signature_algorithm": "AWS-KMS" if TRUST_SIGNING_PROVIDER == "aws_kms" else "HMAC-SHA256",
                         "signing_provider": TRUST_SIGNING_PROVIDER,
                         "kms_key_configured": bool(TRUST_KMS_KEY_ID),
                         "evidence_archive_configured": bool(EVIDENCE_ARCHIVE_BUCKET),
                         "evidence_archive_retention_days": EVIDENCE_ARCHIVE_RETENTION_DAYS,
                         "supabase_auth_enabled": AUTH_MODE in {"hybrid", "supabase"},
                         "supabase_require_aal2": SUPABASE_REQUIRE_AAL2},
            "roles": ROLES, "current_user": {"name": user.name, "email": user.email, "role": user.role},
            "permissions": {"rule_management": user.role == "Brand Admin",
                "manage_users": user.role == "Brand Admin", "publish_signoff": user.role in {"Manager", "SME / Legal", "Brand Admin"},
                "delete_documents": user.role in {"Manager", "Brand Admin"}, "run_rescan": user.role in {"Manager", "SME / Legal", "Brand Admin"}}}


from .capabilities import router as trust_os_router
from .foundation import router as foundation_router
app.include_router(trust_os_router)
app.include_router(foundation_router)

# Keep startup initialization opt-in for scripts that import the module. FastAPI executes startup in normal runs.


# When built for a single-origin deployment (for example Render), serve the Vite
# production bundle from FastAPI. In local development Vite remains a separate server.
_FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST_DIR", str(Path(__file__).resolve().parents[1] / "static"))).resolve()
if (_FRONTEND_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="frontend-assets")


@app.get("/", include_in_schema=False)
def frontend_root():
    index_file = _FRONTEND_DIST / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    return {"app": APP_NAME, "status": "ok", "api_docs": "/docs", "frontend": "Run the Vite dev server from the frontend folder for local development."}


@app.get("/{asset_path:path}", include_in_schema=False)
def frontend_or_not_found(asset_path: str):
    # Preserve normal 404 semantics for unknown API routes rather than serving index.html.
    if asset_path == "api" or asset_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API endpoint not found.")
    candidate = (_FRONTEND_DIST / asset_path).resolve()
    if _FRONTEND_DIST in candidate.parents and candidate.is_file():
        return FileResponse(candidate)
    index_file = _FRONTEND_DIST / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    raise HTTPException(status_code=404, detail="Not found.")
