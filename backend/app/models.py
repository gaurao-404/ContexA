from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

try:
    from pgvector.sqlalchemy import Vector
except ImportError:  # optional for SQLite-only local development
    Vector = None
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
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
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
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
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ContentDocument(Base):
    __tablename__ = "content_documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(160), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    pages_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="IN_REVIEW")
    compliance_score: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
