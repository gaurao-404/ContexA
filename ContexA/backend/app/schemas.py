from __future__ import annotations
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

Role = Literal["Creator", "Manager", "SME / Legal", "Brand Admin"]
Severity = Literal["critical", "warning", "info"]
FindingStatus = Literal["open", "accepted", "dismissed", "edited"]

class CopyCheckRequest(BaseModel):
    text: str = Field(min_length=1, max_length=15000)

class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)
    turnstile_token: str | None = Field(default=None, max_length=2048)

class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=140)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)
    workspace_name: str | None = Field(default=None, max_length=140)
    turnstile_token: str | None = Field(default=None, max_length=2048)

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    email: str
    role: str
    workspace_id: str
    workspace_name: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut

class RuleCreate(BaseModel):
    code: str = Field(min_length=2, max_length=40)
    title: str = Field(min_length=2, max_length=180)
    category: str = Field(min_length=2, max_length=50)
    rule_clause: str = Field(min_length=8)
    source_document: str = "Brand Governance Handbook"
    pattern: str | None = None
    severity: Severity = "warning"
    suggested_fix: str = "Review this content against the approved guideline."
    is_active: bool = True

class RuleUpdate(BaseModel):
    title: str | None = None
    category: str | None = None
    rule_clause: str | None = None
    source_document: str | None = None
    pattern: str | None = None
    severity: Severity | None = None
    suggested_fix: str | None = None
    is_active: bool | None = None

class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    code: str
    title: str
    category: str
    rule_clause: str
    source_document: str
    pattern: str | None
    severity: str
    suggested_fix: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

class FindingAction(BaseModel):
    status: FindingStatus
    note: str | None = None
    applied_text: str | None = None

class FindingOut(BaseModel):
    id: str
    content_id: str
    rule_id: str | None
    rule_code: str | None = None
    rule_title: str | None = None
    severity: str
    finding_type: str
    flagged_text: str
    page_number: int
    location_bbox: dict[str, Any] | None
    reasoning: str
    suggested_fix: str
    applied_text: str | None = None
    status: str
    dismissal_reason: str | None
    created_at: datetime
    updated_at: datetime

class DocumentOut(BaseModel):
    id: str
    filename: str
    content_type: str
    page_count: int
    status: str
    compliance_score: int
    size_bytes: int
    created_by: str
    creator_name: str | None = None
    created_at: datetime
    updated_at: datetime
    findings_count: int = 0
    critical_count: int = 0

class FindingActionResponse(BaseModel):
    finding: FindingOut
    publish_ready: bool

class PublishRequest(BaseModel):
    override_note: str | None = None

class ActivityOut(BaseModel):
    id: str
    actor_name: str
    action: str
    entity_type: str
    entity_id: str
    detail: dict[str, Any]
    created_at: datetime

class DashboardOut(BaseModel):
    integrity_score: int
    total_documents: int
    in_review: int
    publish_ready: int
    open_findings: int
    critical_findings: int
    warning_findings: int
    rule_count: int
    recent_documents: list[DocumentOut]
    recent_activity: list[ActivityOut]
    severity_counts: dict[str, int]
    weekly_activity: list[dict[str, Any]]

class InsightRule(BaseModel):
    id: str
    code: str
    title: str
    category: str
    triggered: int
    dismissed: int
    gci: int
    status: str

class InsightOut(BaseModel):
    rule_clarity_index: int
    total_findings: int
    dismissed_findings: int
    rules: list[InsightRule]
    findings_by_category: dict[str, int]


class FactCreate(BaseModel):
    fact_key: str = Field(min_length=2, max_length=120)
    fact_type: Literal["price", "product_name", "claim", "campaign", "other"] = "other"
    entity_name: str = Field(default="", max_length=180)
    canonical_value: str = Field(min_length=1, max_length=2000)
    currency: str | None = Field(default=None, max_length=8)
    unit: str | None = Field(default=None, max_length=60)
    aliases: list[str] = Field(default_factory=list, max_length=30)
    source_document: str = Field(min_length=2, max_length=255)
    source_quote: str = Field(min_length=8, max_length=4000)
    source_document_id: str | None = None
    source_page: int | None = Field(default=None, ge=1)
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class FactRevision(BaseModel):
    canonical_value: str | None = Field(default=None, min_length=1, max_length=2000)
    entity_name: str | None = Field(default=None, max_length=180)
    currency: str | None = Field(default=None, max_length=8)
    unit: str | None = Field(default=None, max_length=60)
    aliases: list[str] | None = Field(default=None, max_length=30)
    source_document: str | None = Field(default=None, min_length=2, max_length=255)
    source_quote: str | None = Field(default=None, min_length=8, max_length=4000)
    source_document_id: str | None = None
    source_page: int | None = Field(default=None, ge=1)
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class PolicySimulationRequest(BaseModel):
    rule_id: str
    proposed_pattern: str = Field(min_length=1, max_length=1000)


class PolicyApplyRequest(BaseModel):
    change_note: str = Field(min_length=8, max_length=1000)


class ReviewTaskUpdate(BaseModel):
    assigned_to: str | None = None
    status: Literal["open", "in_progress", "completed"] | None = None


class TokenRequest(BaseModel):
    token: str = Field(min_length=20, max_length=256)

class PasswordResetRequest(TokenRequest):
    password: str = Field(min_length=12, max_length=128)

class InvitationCreate(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    role: Literal["Creator", "Manager", "SME / Legal"] = "Creator"

class InvitationAccept(TokenRequest):
    name: str = Field(min_length=2, max_length=140)
    password: str = Field(min_length=12, max_length=128)


class WorkspaceDeleteRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    workspace_name_confirmation: str = Field(min_length=2, max_length=140)
