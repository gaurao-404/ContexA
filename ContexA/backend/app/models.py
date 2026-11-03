from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

try:
    from pgvector.sqlalchemy import Vector
except ImportError:  # optional for SQLite-only local development
    Vector = None
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, LargeBinary, String, Text, UniqueConstraint, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class PortableVector(TypeDecorator):
    """Store a real pgvector column on PostgreSQL and JSON vectors on SQLite."""
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            if Vector is None:
                raise RuntimeError("Install pgvector to use PostgreSQL persistence: pip install pgvector")
            return dialect.type_descriptor(Vector(1536))
        return dialect.type_descriptor(JSON())


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="Creator")
    # Every self-serve account belongs to its own workspace. Invited members share
    # their owner's workspace_id. Request handlers enforce this boundary server-side.
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False, default="ws-contexa-demo")
    workspace_name: Mapped[str] = mapped_column(String(140), nullable=False, default="ContexA Demo Workspace")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Optional external identity link. The provider subject is unique and only linked
    # after a verified-email JWT has been validated server-side.
    supabase_subject: Mapped[str | None] = mapped_column(String(128), unique=True, index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BrandRule(Base):
    __tablename__ = "brand_rules"
    __table_args__ = (UniqueConstraint("workspace_id", "code", name="uq_workspace_rule_code"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    rule_clause: Mapped[str] = mapped_column(Text, nullable=False)
    source_document: Mapped[str] = mapped_column(String(255), nullable=False, default="Brand Governance Handbook")
    pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(20), default="warning", nullable=False)
    suggested_fix: Mapped[str] = mapped_column(Text, default="Review this content against the approved guideline.", nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(PortableVector(), nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False, default="hashed-token-v1")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class GuidelineChunk(Base):
    """Structure-aware searchable chunks retained with source/page provenance."""
    __tablename__ = "guideline_chunks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    source_document: Mapped[str] = mapped_column(String(255), nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    heading: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(PortableVector(), nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False, default="hashed-token-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContentDocument(Base):
    __tablename__ = "content_documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional small-file persistence for ephemeral demo hosts. For large-scale production,
    # replace DB blobs with durable object storage (S3-compatible storage, etc.).
    file_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    content_type: Mapped[str] = mapped_column(String(160), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    pages_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="IN_REVIEW")
    compliance_score: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    scan_status: Mapped[str] = mapped_column(String(24), nullable=False, default="not_configured")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    creator: Mapped[User] = relationship()
    findings: Mapped[list["ReviewFinding"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class ReviewFinding(Base):
    __tablename__ = "review_findings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    content_id: Mapped[str] = mapped_column(ForeignKey("content_documents.id", ondelete="CASCADE"), index=True, nullable=False)
    rule_id: Mapped[str | None] = mapped_column(ForeignKey("brand_rules.id"), nullable=True)
    rule_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="warning")
    finding_type: Mapped[str] = mapped_column(String(50), nullable=False)
    flagged_text: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    location_bbox: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_fix: Mapped[str] = mapped_column(Text, nullable=False)
    applied_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    dismissal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    document: Mapped[ContentDocument] = relationship(back_populates="findings")
    rule: Mapped[BrandRule | None] = relationship()


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_name: Mapped[str] = mapped_column(String(140), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RuleVersion(Base):
    """Immutable snapshot of a published or draft brand-rule revision."""
    __tablename__ = "rule_versions"
    __table_args__ = (UniqueConstraint("rule_id", "version_number", name="uq_rule_version_number"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    rule_id: Mapped[str] = mapped_column(ForeignKey("brand_rules.id", ondelete="CASCADE"), index=True, nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    change_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApprovedFact(Base):
    """Versioned source of truth for prices, product names, claims and other approved facts."""
    __tablename__ = "approved_facts"
    __table_args__ = (UniqueConstraint("workspace_id", "fact_key", "version_number", name="uq_fact_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    fact_key: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    fact_type: Mapped[str] = mapped_column(String(40), index=True, nullable=False, default="other")
    entity_name: Mapped[str] = mapped_column(String(180), nullable=False, default="")
    canonical_value: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(60), nullable=True)
    source_document: Mapped[str] = mapped_column(String(255), nullable=False)
    source_quote: Mapped[str] = mapped_column(Text, nullable=False)
    source_document_id: Mapped[str | None] = mapped_column(ForeignKey("content_documents.id", ondelete="SET NULL"), nullable=True)
    source_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    supersedes_id: Mapped[str | None] = mapped_column(ForeignKey("approved_facts.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScanRun(Base):
    __tablename__ = "scan_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("content_documents.id", ondelete="SET NULL"), index=True, nullable=True)
    initiated_by: Mapped[str] = mapped_column(String(36), nullable=False)
    engine_mode: Mapped[str] = mapped_column(String(40), nullable=False, default="deterministic")
    ruleset_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    total_findings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verified_evidence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unverifiable_evidence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FindingEvidence(Base):
    __tablename__ = "finding_evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    finding_id: Mapped[str] = mapped_column(ForeignKey("review_findings.id", ondelete="CASCADE"), index=True, nullable=False)
    scan_run_id: Mapped[str | None] = mapped_column(ForeignKey("scan_runs.id", ondelete="SET NULL"), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_label: Mapped[str] = mapped_column(String(255), nullable=False)
    source_quote: Mapped[str] = mapped_column(Text, nullable=False)
    content_quote: Mapped[str] = mapped_column(Text, nullable=False)
    locator: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    verification_status: Mapped[str] = mapped_column(String(24), nullable=False, default="grounded")
    match_score: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PolicySimulation(Base):
    __tablename__ = "policy_simulations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    rule_id: Mapped[str | None] = mapped_column(ForeignKey("brand_rules.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    rule_code: Mapped[str] = mapped_column(String(40), nullable=False)
    proposed_pattern: Mapped[str] = mapped_column(Text, nullable=False)
    documents_scanned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    documents_affected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matches_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sample_matches: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvaluationCase(Base):
    __tablename__ = "evaluation_cases"
    __table_args__ = (UniqueConstraint("workspace_id", "case_code", name="uq_eval_case_code"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    case_code: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    expected_rule_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="general")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    initiated_by: Mapped[str] = mapped_column(String(36), nullable=False)
    case_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    true_positives: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    false_positives: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    false_negatives: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    precision: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    recall: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    f1_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    details: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReviewTask(Base):
    __tablename__ = "review_tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("content_documents.id", ondelete="CASCADE"), index=True, nullable=False)
    assigned_role: Mapped[str] = mapped_column(String(40), nullable=False)
    assigned_to: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BrandAsset(Base):
    """Workspace-owned canonical logo, font, template, color and other brand asset."""
    __tablename__ = "brand_assets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False, default="other")
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(160), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    file_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuthActionToken(Base):
    """Hashed, one-time token for email verification, password reset and invitations."""
    __tablename__ = "auth_action_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True)
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LoginAttempt(Base):
    """Persistent login throttling state keyed by normalized email and client address."""
    __tablename__ = "login_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    identity_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

# ContexA Trust OS extensions (additive, workspace-scoped records).
class MonitoredSource(Base):
    __tablename__ = "monitored_sources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    authority: Mapped[str] = mapped_column(String(120), nullable=False, default="Workspace supplied")
    source_type: Mapped[str] = mapped_column(String(30), nullable=False, default="official")
    last_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    last_excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_status: Mapped[str] = mapped_column(String(30), nullable=False, default="never_checked")
    last_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TruthDriftEvent(Base):
    __tablename__ = "truth_drift_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("monitored_sources.id", ondelete="SET NULL"), nullable=True)
    fact_id: Mapped[str | None] = mapped_column(ForeignKey("approved_facts.id", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="warning")
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    previous_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    current_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TrustPassport(Base):
    __tablename__ = "trust_passports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("content_documents.id", ondelete="CASCADE"), index=True, nullable=False)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    asset_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    signature: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    issued_by: Mapped[str] = mapped_column(String(36), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PublicPassportIndex(Base):
    """Minimal, intentionally public lookup index for QR verification.

    This table contains only the signed public attestation fields. It deliberately
    has no workspace_id and is not covered by tenant RLS, so unauthenticated QR
    verification works with PostgreSQL FORCE RLS without granting public access
    to the workspace-owned passport or document tables.
    """
    __tablename__ = "public_passport_index"
    public_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    passport_id: Mapped[str] = mapped_column(ForeignKey("trust_passports.id", ondelete="CASCADE"), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    asset_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    signature: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MediaInspection(Base):
    __tablename__ = "media_inspections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(40), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    findings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    capability_status: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("content_documents.id", ondelete="SET NULL"), nullable=True)
    objective: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="completed")
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    outputs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    initiated_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DigitalTwinScenario(Base):
    __tablename__ = "digital_twin_scenarios"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    scenario_type: Mapped[str] = mapped_column(String(40), nullable=False)
    proposed_changes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    impact_report: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="simulated")
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LanguageReview(Base):
    __tablename__ = "language_reviews"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    language: Mapped[str] = mapped_column(String(40), nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    localized_text: Mapped[str] = mapped_column(Text, nullable=False)
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="human_review_required")
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RegulatoryRequirement(Base):
    __tablename__ = "regulatory_requirements"
    __table_args__ = (UniqueConstraint("workspace_id", "requirement_code", name="uq_reg_requirement_code"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    requirement_code: Mapped[str] = mapped_column(String(60), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(80), nullable=False)
    industry: Mapped[str] = mapped_column(String(100), nullable=False, default="General")
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    authority: Mapped[str] = mapped_column(String(160), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    requirement_summary: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_terms: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    required_terms: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    effective_from: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_version: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RegulatoryAssessment(Base):
    __tablename__ = "regulatory_assessments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("content_documents.id", ondelete="SET NULL"), nullable=True)
    assessment_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(80), nullable=False)
    requirement_code: Mapped[str] = mapped_column(String(60), nullable=False)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BrandIncident(Base):
    __tablename__ = "brand_incidents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    incident_code: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")
    source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    affected_document_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    timeline: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# Enterprise Trust Foundation: additive graph, replay, archive and signature records.
class EvidenceGraphNode(Base):
    __tablename__ = "evidence_graph_nodes"
    __table_args__ = (UniqueConstraint("workspace_id", "node_type", "external_id", name="uq_graph_node_external"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    node_type: Mapped[str] = mapped_column(String(40), nullable=False)
    external_id: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(240), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvidenceGraphEdge(Base):
    __tablename__ = "evidence_graph_edges"
    __table_args__ = (UniqueConstraint("workspace_id", "source_node_id", "target_node_id", "relation", name="uq_graph_edge_relation"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    source_node_id: Mapped[str] = mapped_column(ForeignKey("evidence_graph_nodes.id", ondelete="CASCADE"), index=True, nullable=False)
    target_node_id: Mapped[str] = mapped_column(ForeignKey("evidence_graph_nodes.id", ondelete="CASCADE"), index=True, nullable=False)
    relation: Mapped[str] = mapped_column(String(60), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DecisionTrace(Base):
    __tablename__ = "decision_traces"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    agent_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"), index=True, nullable=True)
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    model_id: Mapped[str] = mapped_column(String(160), nullable=False, default="deterministic-policy-engine")
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False, default="deterministic-rules-v1")
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    output_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    trace: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    integrity_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvidenceArchive(Base):
    __tablename__ = "evidence_archives"
    __table_args__ = (UniqueConstraint("workspace_id", "subject_type", "subject_id", name="uq_evidence_archive_subject"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    subject_type: Mapped[str] = mapped_column(String(60), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(100), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    storage_provider: Mapped[str] = mapped_column(String(40), nullable=False)
    object_lock_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    retain_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="stored_non_immutable")
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PassportSignature(Base):
    """Public verification metadata. Contains only public key/signature material."""
    __tablename__ = "passport_signatures"
    public_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    passport_id: Mapped[str] = mapped_column(ForeignKey("trust_passports.id", ondelete="CASCADE"), unique=True, nullable=False)
    signing_provider: Mapped[str] = mapped_column(String(40), nullable=False)
    signing_key_id: Mapped[str] = mapped_column(String(240), nullable=False)
    signing_algorithm: Mapped[str] = mapped_column(String(80), nullable=False)
    signature_b64: Mapped[str] = mapped_column(Text, nullable=False)
    public_key_b64: Mapped[str | None] = mapped_column(Text, nullable=True)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    verification_method: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvidenceMerkleAnchor(Base):
    __tablename__ = "evidence_merkle_anchors"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    leaf_count: Mapped[int] = mapped_column(Integer, nullable=False)
    root_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_anchor_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    signing_provider: Mapped[str] = mapped_column(String(40), nullable=False)
    signing_key_id: Mapped[str] = mapped_column(String(240), nullable=False)
    signature_algorithm: Mapped[str] = mapped_column(String(80), nullable=False)
    signature_b64: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------------------
# Round 4 — collaboration, analytics history and operations
# ---------------------------------------------------------------------------

class Notification(Base):
    """In-app notification addressed to one workspace member."""
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)  # review_task | mention | publish | critical_finding | system
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    entity_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Comment(Base):
    """Threaded discussion attached to a document or a finding."""
    __tablename__ = "comments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)  # document | finding
    entity_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    author_id: Mapped[str] = mapped_column(String(36), nullable=False)
    author_name: Mapped[str] = mapped_column(String(140), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    mentions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)  # user ids
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ComplianceSnapshot(Base):
    """One row per workspace per UTC day: the real compliance posture at that time."""
    __tablename__ = "compliance_snapshots"
    __table_args__ = (UniqueConstraint("workspace_id", "snapshot_date", name="uq_snapshot_workspace_day"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    snapshot_date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    integrity_score: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    total_documents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    publish_ready: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    open_findings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    critical_findings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_findings: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    open_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_rules: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
