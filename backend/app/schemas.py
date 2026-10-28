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
    email: str
    password: str

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    email: str
    role: str

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
