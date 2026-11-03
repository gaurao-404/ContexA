"""ContexA Trust OS capabilities.

Deterministic services are deliberately explicit about their limits: source-change
signals are not proof of a false claim, OCR is not semantic verification, and
regulatory keyword checks are review prompts rather than legal opinions.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import http.client
import ipaddress
import io
import json
import re
import shutil
import socket
import subprocess
import tempfile
import uuid
import unicodedata
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request as FastAPIRequest, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import desc, select, func, text
from sqlalchemy.orm import Session

from .config import (PUBLIC_APP_URL, TRUST_PASSPORT_SIGNING_KEY, TRUTH_DRIFT_CRON_TOKEN,
                     SECRET_KEY, UPLOAD_MAX_PER_USER, UPLOAD_WINDOW_MINUTES)
from .database import engine, get_db, set_workspace_context
from .models import (
    AgentRun, ApprovedFact, AuditEvent, BrandIncident, BrandRule, ContentDocument,
    DigitalTwinScenario, LanguageReview, MediaInspection, MonitoredSource,
    RegulatoryAssessment, RegulatoryRequirement, ReviewFinding, ReviewTask,
    TrustPassport, PublicPassportIndex, PassportSignature, TruthDriftEvent, User, LoginAttempt, utcnow, new_id,
)
from .security import get_current_user, require_roles
from .parsing import parse_document, parse_image
from .upload_security import read_upload_limited, sha256_hex

router = APIRouter(prefix="/api", tags=["ContexA Trust OS"])


class SourceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    source_url: str = Field(min_length=8, max_length=2000)
    authority: str = Field(default="Workspace supplied", max_length=120)
    source_type: str = Field(default="official", max_length=30)


class AgentRequest(BaseModel):
    objective: str = Field(default="Review this content for brand trust risks", max_length=240)
    document_id: str | None = None
    content_text: str | None = Field(default=None, max_length=100_000)


class TwinRequest(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    scenario_type: str = Field(default="fact_change", max_length=40)
    proposed_changes: dict[str, Any] = Field(default_factory=dict)


class LanguageRequest(BaseModel):
    language: str = Field(min_length=2, max_length=40)
    source_text: str = Field(min_length=1, max_length=20_000)
    localized_text: str = Field(min_length=1, max_length=20_000)


class IncidentCreate(BaseModel):
    title: str = Field(min_length=3, max_length=240)
    description: str = Field(min_length=5, max_length=10_000)
    severity: str = "medium"
    source_type: str = "manual"
    source_id: str | None = None
    affected_document_ids: list[str] = Field(default_factory=list, max_length=100)


class IncidentUpdate(BaseModel):
    status: str
    note: str | None = Field(default=None, max_length=4000)
    resolution: str | None = Field(default=None, max_length=4000)


class RegulatoryAssessmentRequest(BaseModel):
    document_id: str | None = None
    content_text: str | None = Field(default=None, max_length=100_000)


class RegulatoryCreate(BaseModel):
    requirement_code: str = Field(min_length=3, max_length=60)
    jurisdiction: str = Field(min_length=2, max_length=80)
    industry: str = Field(default="General", max_length=100)
    title: str = Field(min_length=3, max_length=220)
    authority: str = Field(min_length=2, max_length=160)
    source_url: str = Field(min_length=8, max_length=2000)
    requirement_summary: str = Field(min_length=10, max_length=10_000)
    trigger_terms: list[str] = Field(default_factory=list, max_length=100)
    required_terms: list[str] = Field(default_factory=list, max_length=100)
    effective_from: str | None = None
    source_version: str = ""


class PassportCreate(BaseModel):
    document_id: str
    title: str | None = Field(default=None, max_length=240)
    include_public_claims: bool = False


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.hidden = 0
    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}: self.hidden += 1
    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self.hidden: self.hidden -= 1
    def handle_data(self, data):
        if not self.hidden and data.strip(): self.parts.append(data.strip())


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "Redirect blocked; configure the final canonical URL directly", headers, fp)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _consume_media_inspection_limit(db: Session, user: User) -> None:
    """Persistently throttle expensive media parsing per authenticated user."""
    identity = hmac.new(SECRET_KEY.encode("utf-8"), f"trustos-media|{user.id}".encode("utf-8"), hashlib.sha256).hexdigest()
    now = _now()
    row = db.scalar(select(LoginAttempt).where(LoginAttempt.identity_hash == identity))
    if row is None:
        row = LoginAttempt(identity_hash=identity, failures=0, window_started_at=now)
        db.add(row)
    window_started = row.window_started_at
    locked_until = row.locked_until
    if window_started.tzinfo is None:
        window_started = window_started.replace(tzinfo=timezone.utc)
    if locked_until and locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    if locked_until and locked_until > now:
        raise HTTPException(429, "Media inspection limit reached for this account. Try again after the upload window resets.")
    if window_started + timedelta(minutes=UPLOAD_WINDOW_MINUTES) < now:
        row.failures = 0
        row.window_started_at = now
        row.locked_until = None
    row.failures += 1
    if row.failures > UPLOAD_MAX_PER_USER:
        row.locked_until = now + timedelta(minutes=UPLOAD_WINDOW_MINUTES)
        db.commit()
        raise HTTPException(429, "Media inspection limit reached for this account. Try again after the upload window resets.")
    db.commit()


def _audit(db: Session, user: User, action: str, entity_type: str, entity_id: str,
           detail: dict[str, Any] | None = None) -> None:
    if engine.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:workspace_id))"), {"workspace_id": user.workspace_id})
    previous = db.scalar(select(AuditEvent).where(AuditEvent.workspace_id == user.workspace_id)
                         .order_by(desc(AuditEvent.created_at), desc(AuditEvent.id)).limit(1))
    previous_hash = previous.event_hash if previous and previous.event_hash else ("0" * 64)
    event = AuditEvent(id=new_id(), workspace_id=user.workspace_id, actor_id=user.id, actor_name=user.name,
                       action=action, entity_type=entity_type, entity_id=entity_id,
                       detail=detail or {}, previous_hash=previous_hash, created_at=utcnow())
    payload = {"id": event.id, "workspace_id": event.workspace_id, "actor_id": event.actor_id,
               "actor_name": event.actor_name, "action": event.action, "entity_type": event.entity_type,
               "entity_id": event.entity_id, "detail": event.detail or {},
               "created_at": event.created_at.isoformat(), "previous_hash": previous_hash}
    event.event_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()).hexdigest()
    db.add(event)


def _resolve_public_ip(host: str, port: int = 443) -> str:
    """Resolve and pin one public address to prevent DNS-rebinding SSRF.

    Every answer must be globally routable; the HTTPS socket connects to the
    selected IP while TLS still verifies and sends SNI for the original hostname.
    """
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("Source host could not be resolved.") from exc
    ips = []
    for info in addresses:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError as exc:
            raise ValueError("Source host returned an invalid IP address.") from exc
        if not ip.is_global:
            raise ValueError("Source host resolved to a non-public IP address.")
        ips.append(str(ip))
    if not ips:
        raise ValueError("Source host did not resolve to a public IP address.")
    return ips[0]


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, *, pinned_ip: str, **kwargs):
        self._pinned_ip = pinned_ip
        super().__init__(host, **kwargs)

    def connect(self):
        sock = socket.create_connection((self._pinned_ip, self.port), self.timeout, self.source_address)
        if self._tunnel_host:
            self._tunnel()
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _PinnedHTTPSHandler(HTTPSHandler):
    def __init__(self, pinned_ip: str):
        super().__init__()
        self._pinned_ip = pinned_ip

    def https_open(self, req):
        return self.do_open(
            lambda host, **kwargs: _PinnedHTTPSConnection(host, pinned_ip=self._pinned_ip, **kwargs),
            req, context=self._context, check_hostname=self._check_hostname,
        )


def _public_host(host: str) -> bool:
    try:
        _resolve_public_ip(host, 443)
        return True
    except (ValueError, OSError):
        return False


def _fetch_source(url: str) -> tuple[str, int, str]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only credential-free HTTPS source URLs are allowed.")
    port = parsed.port or 443
    pinned_ip = _resolve_public_ip(parsed.hostname, port)
    req = Request(url, headers={"User-Agent": "ContexA-SourceMonitor/1.0", "Accept": "text/html,text/plain,application/pdf"})
    # Disable environment proxy settings: an ambient proxy must not bypass the
    # public-IP validation and pinned destination enforced above.
    opener = build_opener(ProxyHandler({}), _NoRedirect(), _PinnedHTTPSHandler(pinned_ip))
    with opener.open(req, timeout=8) as response:
        status = int(response.status)
        content_type = response.headers.get_content_type()
        raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("Source response exceeded the 1 MB monitoring limit.")
    if content_type == "application/pdf":
        import fitz
        doc = fitz.open(stream=raw, filetype="pdf")
        try: content = "\n".join(page.get_text("text") for page in doc)
        finally: doc.close()
    elif content_type in {"text/html", "application/xhtml+xml"}:
        parser = _VisibleText(); parser.feed(raw.decode("utf-8", errors="replace")); content = "\n".join(parser.parts)
    elif content_type.startswith("text/") or content_type in {"application/json", "application/xml"}:
        content = raw.decode("utf-8", errors="replace")
    else:
        raise ValueError(f"Unsupported monitored source content type: {content_type}")
    content = re.sub(r"\s+", " ", html.unescape(content)).strip()
    return content, status, content_type


def _source_out(item: MonitoredSource) -> dict[str, Any]:
    return {"id": item.id, "name": item.name, "source_url": item.source_url, "authority": item.authority,
            "source_type": item.source_type, "last_status": item.last_status, "last_http_status": item.last_http_status,
            "last_checked_at": item.last_checked_at.isoformat() if item.last_checked_at else None,
            "is_active": item.is_active, "created_at": item.created_at.isoformat()}


def _drift_out(item: TruthDriftEvent) -> dict[str, Any]:
    return {"id": item.id, "source_id": item.source_id, "fact_id": item.fact_id, "event_type": item.event_type,
            "severity": item.severity, "title": item.title, "detail": item.detail, "evidence": item.evidence,
            "status": item.status, "detected_at": item.detected_at.isoformat(),
            "resolved_at": item.resolved_at.isoformat() if item.resolved_at else None}


def _incident_out(item: BrandIncident) -> dict[str, Any]:
    return {"id": item.id, "incident_code": item.incident_code, "title": item.title,
            "description": item.description, "severity": item.severity, "status": item.status,
            "source_type": item.source_type, "source_id": item.source_id,
            "affected_document_ids": item.affected_document_ids, "owner_id": item.owner_id,
            "timeline": item.timeline, "resolution": item.resolution,
            "created_at": item.created_at.isoformat(), "updated_at": item.updated_at.isoformat()}


def _new_incident(db: Session, user: User, title: str, description: str, severity: str,
                  source_type: str, source_id: str | None, affected: list[str]) -> BrandIncident:
    count = db.scalar(select(func.count(BrandIncident.id)).where(BrandIncident.workspace_id == user.workspace_id)) or 0
    item = BrandIncident(workspace_id=user.workspace_id, incident_code=f"CTX-{_now():%y%m}-{count + 1:04d}",
        title=title[:240], description=description[:10000], severity=severity,
        status="open", source_type=source_type, source_id=source_id,
        affected_document_ids=affected[:100], created_by=user.id,
        timeline=[{"at": _now().isoformat(), "action": "created", "actor": user.name, "note": "Incident opened."}])
    db.add(item); db.flush()
    return item


@router.get("/trust-os/overview")
def trust_os_overview(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    w = user.workspace_id
    counts = {
        "sources": db.scalar(select(func.count(MonitoredSource.id)).where(MonitoredSource.workspace_id == w, MonitoredSource.is_active.is_(True))) or 0,
        "open_drift": db.scalar(select(func.count(TruthDriftEvent.id)).where(TruthDriftEvent.workspace_id == w, TruthDriftEvent.status == "open")) or 0,
        "passports": db.scalar(select(func.count(TrustPassport.id)).where(TrustPassport.workspace_id == w, TrustPassport.status == "active")) or 0,
        "media_reviews": db.scalar(select(func.count(MediaInspection.id)).where(MediaInspection.workspace_id == w)) or 0,
        "agent_runs": db.scalar(select(func.count(AgentRun.id)).where(AgentRun.workspace_id == w)) or 0,
        "scenarios": db.scalar(select(func.count(DigitalTwinScenario.id)).where(DigitalTwinScenario.workspace_id == w)) or 0,
        "incidents_open": db.scalar(select(func.count(BrandIncident.id)).where(BrandIncident.workspace_id == w, BrandIncident.status != "resolved")) or 0,
    }
    return {"metrics": counts, "principles": ["source signals are not truth decisions", "machine findings require appropriate review", "regulatory assessments are not legal advice"]}


# Truth Drift Radar ---------------------------------------------------------
@router.get("/truth-drift/sources")
def list_truth_sources(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(MonitoredSource).where(MonitoredSource.workspace_id == user.workspace_id).order_by(desc(MonitoredSource.created_at))).all()
    return [_source_out(x) for x in rows]


@router.post("/truth-drift/sources", status_code=201)
def create_truth_source(payload: SourceCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("Manager", "SME / Legal", "Brand Admin"))):
    parsed = urlparse(payload.source_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise HTTPException(422, "Source must be an HTTPS URL.")
    if not _public_host(parsed.hostname):
        raise HTTPException(422, "Source hostname must resolve to public IP addresses only.")
    item = MonitoredSource(workspace_id=user.workspace_id, name=payload.name.strip(), source_url=payload.source_url,
        authority=payload.authority.strip(), source_type=payload.source_type, created_by=user.id)
    db.add(item); db.flush()
    _audit(db, user, "truth_source.created", "monitored_source", item.id, {"name": item.name})
    db.commit(); db.refresh(item); return _source_out(item)


@router.post("/truth-drift/sources/{source_id}/scan")
def scan_truth_source(source_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("Manager", "SME / Legal", "Brand Admin"))):
    item = db.scalar(select(MonitoredSource).where(MonitoredSource.id == source_id, MonitoredSource.workspace_id == user.workspace_id, MonitoredSource.is_active.is_(True)))
    if not item: raise HTTPException(404, "Monitored source not found.")
    try:
        content, status, content_type = _fetch_source(item.source_url)
    except (ValueError, HTTPError, URLError, TimeoutError, OSError) as exc:
        item.last_status = "fetch_error"; item.last_checked_at = utcnow(); db.commit()
        raise HTTPException(502, f"Source could not be checked safely: {str(exc)[:300]}")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    previous = item.last_sha256
    changed = bool(previous and previous != digest)
    item.last_http_status = status; item.last_checked_at = utcnow(); item.last_status = "changed" if changed else "baseline" if not previous else "unchanged"
    event_out = None; incident_out = None
    if changed:
        old_text = item.last_excerpt or ""
        active_facts = db.scalars(select(ApprovedFact).where(ApprovedFact.workspace_id == user.workspace_id, ApprovedFact.status == "approved")).all()
        affected = []
        for fact in active_facts:
            old_supported = bool(fact.canonical_value and fact.canonical_value.lower() in old_text.lower())
            current_supported = bool(fact.canonical_value and fact.canonical_value.lower() in content.lower())
            if old_supported and not current_supported: affected.append(fact)
        event = TruthDriftEvent(workspace_id=user.workspace_id, source_id=item.id, event_type="source_changed",
            severity="high" if affected else "medium", title=f"Source changed: {item.name}",
            detail=(f"The monitored source changed since the previous successful scan. {len(affected)} approved fact(s) that appeared in the previous snapshot are no longer present in the new snapshot. This is a review signal, not proof that the facts are false."),
            previous_sha256=previous, current_sha256=digest,
            evidence={"content_type": content_type, "http_status": status, "affected_facts": [{"id": f.id, "fact_key": f.fact_key, "old_value": f.canonical_value} for f in affected], "new_excerpt": content[:1200]})
        db.add(event); db.flush(); event_out = _drift_out(event)
        incident = _new_incident(db, user, f"Truth drift: {item.name}", event.detail, event.severity, "truth_drift", event.id, [])
        incident_out = _incident_out(incident)
    item.last_sha256 = digest; item.last_excerpt = content[:20000]
    _audit(db, user, "truth_drift.source_scanned", "monitored_source", item.id, {"changed": changed, "sha256": digest, "affected_event": event_out["id"] if event_out else None})
    db.commit(); db.refresh(item)
    return {"source": _source_out(item), "changed": changed, "event": event_out, "incident": incident_out,
            "content_type": content_type, "characters_checked": len(content), "sha256": digest}


@router.post("/truth-drift/scan-expired-facts")
def scan_expired_facts(db: Session = Depends(get_db), user: User = Depends(require_roles("Manager", "SME / Legal", "Brand Admin"))):
    now = utcnow()
    facts = db.scalars(select(ApprovedFact).where(ApprovedFact.workspace_id == user.workspace_id, ApprovedFact.status == "approved", ApprovedFact.valid_until.is_not(None))).all()
    created = []
    for fact in facts:
        until = fact.valid_until
        if until and until.tzinfo is None: until = until.replace(tzinfo=timezone.utc)
        if until and until < now:
            existing = db.scalar(select(TruthDriftEvent).where(TruthDriftEvent.workspace_id == user.workspace_id, TruthDriftEvent.fact_id == fact.id, TruthDriftEvent.event_type == "fact_expired", TruthDriftEvent.status == "open"))
            if not existing:
                event = TruthDriftEvent(workspace_id=user.workspace_id, fact_id=fact.id, event_type="fact_expired", severity="high",
                    title=f"Approved fact expired: {fact.entity_name or fact.fact_key}",
                    detail="The validity window for this approved fact has elapsed. Reverify its source and obtain approval before reuse.",
                    evidence={"fact_key": fact.fact_key, "value": fact.canonical_value, "valid_until": until.isoformat(), "source": fact.source_document})
                db.add(event); db.flush(); created.append(_drift_out(event))
                _new_incident(db, user, event.title, event.detail, "high", "truth_drift", event.id, [])
    _audit(db, user, "truth_drift.expiry_scan", "workspace", user.workspace_id, {"new_events": len(created)})
    db.commit(); return {"created": len(created), "events": created}


@router.get("/truth-drift/events")
def list_truth_drift_events(status: str | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = select(TruthDriftEvent).where(TruthDriftEvent.workspace_id == user.workspace_id)
    if status: q = q.where(TruthDriftEvent.status == status)
    rows = db.scalars(q.order_by(desc(TruthDriftEvent.detected_at)).limit(200)).all()
    return [_drift_out(x) for x in rows]


@router.post("/truth-drift/events/{event_id}/resolve")
def resolve_truth_drift_event(event_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("Manager", "SME / Legal", "Brand Admin"))):
    item = db.scalar(select(TruthDriftEvent).where(TruthDriftEvent.id == event_id, TruthDriftEvent.workspace_id == user.workspace_id))
    if not item: raise HTTPException(404, "Drift event not found.")
    item.status = "resolved"; item.resolved_at = utcnow()
    _audit(db, user, "truth_drift.event_resolved", "truth_drift_event", item.id)
    db.commit(); return _drift_out(item)




# Scheduled source monitoring ------------------------------------------------
def _system_audit(db: Session, workspace_id: str, action: str, entity_type: str,
                  entity_id: str, detail: dict[str, Any]) -> None:
    if engine.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:workspace_id))"), {"workspace_id": workspace_id})
    previous = db.scalar(select(AuditEvent).where(AuditEvent.workspace_id == workspace_id)
                         .order_by(desc(AuditEvent.created_at), desc(AuditEvent.id)).limit(1))
    previous_hash = previous.event_hash if previous and previous.event_hash else ("0" * 64)
    event = AuditEvent(workspace_id=workspace_id, actor_id="system:truth-drift-scheduler",
        actor_name="ContexA Truth Drift Scheduler", action=action, entity_type=entity_type,
        entity_id=entity_id, detail=detail, previous_hash=previous_hash)
    payload = {"id": event.id, "workspace_id": workspace_id, "actor_id": event.actor_id,
        "actor_name": event.actor_name, "action": action, "entity_type": entity_type,
        "entity_id": entity_id, "detail": detail, "created_at": event.created_at.isoformat(),
        "previous_hash": previous_hash}
    event.event_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()).hexdigest()
    db.add(event)


@router.post("/internal/truth-drift/scan-due")
def scheduled_truth_drift_scan(request: FastAPIRequest, db: Session = Depends(get_db)):
    """Cloudflare Cron target. Requires a dedicated server-side token; never browser callable."""
    if not TRUTH_DRIFT_CRON_TOKEN:
        raise HTTPException(503, "Scheduled truth monitoring is not configured.")
    supplied = request.headers.get("authorization", "")
    expected = f"Bearer {TRUTH_DRIFT_CRON_TOKEN}"
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "Invalid scheduler credential.")

    workspaces = db.scalars(select(User.workspace_id).where(User.is_active.is_(True)).distinct()).all()
    summary = {"workspaces_checked": 0, "sources_checked": 0, "sources_changed": 0,
               "incidents_created": 0, "errors": []}
    for workspace_id in workspaces:
        set_workspace_context(db, workspace_id)
        summary["workspaces_checked"] += 1
        sources = db.scalars(select(MonitoredSource).where(
            MonitoredSource.workspace_id == workspace_id, MonitoredSource.is_active.is_(True))).all()
        for source in sources:
            try:
                content, status, content_type = _fetch_source(source.source_url)
                digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
                previous = source.last_sha256
                changed = bool(previous and previous != digest)
                source.last_http_status = status
                source.last_checked_at = utcnow()
                source.last_status = "changed" if changed else "baseline" if not previous else "unchanged"
                summary["sources_checked"] += 1
                if changed:
                    old_text = source.last_excerpt or ""
                    facts = db.scalars(select(ApprovedFact).where(
                        ApprovedFact.workspace_id == workspace_id, ApprovedFact.status == "approved")).all()
                    affected = [fact for fact in facts if fact.canonical_value and
                                fact.canonical_value.casefold() in old_text.casefold() and
                                fact.canonical_value.casefold() not in content.casefold()]
                    event = TruthDriftEvent(workspace_id=workspace_id, source_id=source.id,
                        event_type="source_changed", severity="high" if affected else "medium",
                        title=f"Source changed: {source.name}",
                        detail=(f"A scheduled scan detected a content change. {len(affected)} previously represented approved fact(s) are no longer present in the new snapshot. This is a review signal, not proof that the facts are false."),
                        previous_sha256=previous, current_sha256=digest,
                        evidence={"content_type": content_type, "http_status": status,
                            "affected_facts": [{"id": f.id, "fact_key": f.fact_key, "old_value": f.canonical_value} for f in affected],
                            "new_excerpt": content[:1200]})
                    db.add(event); db.flush()
                    count = db.scalar(select(func.count(BrandIncident.id)).where(BrandIncident.workspace_id == workspace_id)) or 0
                    incident = BrandIncident(workspace_id=workspace_id, incident_code=f"CTX-{_now():%y%m}-{count + 1:04d}",
                        title=event.title, description=event.detail, severity=event.severity, status="open",
                        source_type="truth_drift", source_id=event.id, affected_document_ids=[],
                        created_by="system:truth-drift-scheduler",
                        timeline=[{"at": _now().isoformat(), "action": "created", "actor": "ContexA Scheduler", "note": "Created from scheduled source-change detection."}])
                    db.add(incident); db.flush()
                    _system_audit(db, workspace_id, "truth_drift.scheduled_change_detected", "monitored_source", source.id,
                                  {"changed": True, "event_id": event.id, "incident_id": incident.id, "sha256": digest})
                    summary["sources_changed"] += 1
                    summary["incidents_created"] += 1
                source.last_sha256 = digest
                source.last_excerpt = content[:20000]
                db.commit()
            except Exception as exc:
                db.rollback()
                summary["errors"].append({"source_id": source.id, "error": str(exc)[:240]})
                # Restore tenant scope after rollback before moving to another source.
                set_workspace_context(db, workspace_id)
    return summary


# Trust Passport ------------------------------------------------------------
def _passport_payload_signature(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    return hmac.new(TRUST_PASSPORT_SIGNING_KEY.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


@router.post("/trust-passports", status_code=201)
def issue_trust_passport(payload: PassportCreate, request: FastAPIRequest, db: Session = Depends(get_db), user: User = Depends(require_roles("Manager", "SME / Legal", "Brand Admin"))):
    doc = db.scalar(select(ContentDocument).where(ContentDocument.id == payload.document_id, ContentDocument.workspace_id == user.workspace_id))
    if not doc: raise HTTPException(404, "Document not found.")
    if doc.status != "PUBLISH_READY": raise HTTPException(409, "Trust Passport can only be issued after publication sign-off.")
    open_critical = db.scalar(select(func.count(ReviewFinding.id)).where(ReviewFinding.content_id == doc.id, ReviewFinding.severity == "critical", ReviewFinding.status == "open")) or 0
    if open_critical: raise HTTPException(409, "Open critical findings block Trust Passport issuance.")
    if not doc.sha256: raise HTTPException(409, "Document hash is missing. Rescan or re-upload before issuing a passport.")
    facts = db.scalars(select(ApprovedFact).where(ApprovedFact.workspace_id == user.workspace_id, ApprovedFact.status == "approved")).all()
    now = utcnow(); valid_facts = []
    for fact in facts:
        valid_until = fact.valid_until
        if valid_until and valid_until.tzinfo is None: valid_until = valid_until.replace(tzinfo=timezone.utc)
        if valid_until and valid_until < now: continue
        valid_facts.append(fact)
    public_id = uuid.uuid4().hex
    payload_data = {"schema": "contexa-trust-passport/1.0", "public_id": public_id,
        "title": payload.title or doc.filename, "asset_sha256": doc.sha256, "document_id": doc.id,
        "issued_at": now.isoformat(), "issued_by_role": user.role, "verification": {
            "publication_signoff": True, "open_critical_findings": open_critical,
            "review_findings_total": db.scalar(select(func.count(ReviewFinding.id)).where(ReviewFinding.content_id == doc.id)) or 0,
            "active_approved_facts_available": len(valid_facts), "content_sha256_algorithm": "SHA-256"},
        "public_claims": ([{"fact_key": f.fact_key, "entity": f.entity_name, "value": f.canonical_value, "source": f.source_document, "version": f.version_number} for f in valid_facts[:50]] if payload.include_public_claims else []),
        "public_claims_enabled": payload.include_public_claims}
    signature = _passport_payload_signature(payload_data)
    item = TrustPassport(workspace_id=user.workspace_id, document_id=doc.id, public_id=public_id,
        title=payload_data["title"], asset_sha256=doc.sha256, payload=payload_data, signature=signature,
        issued_by=user.id, status="active")
    db.add(item)
    db.flush()
    # The public index is a minimal signed attestation, not a backdoor into tenant data.
    # It is deliberately separated from the workspace-scoped passport row for FORCE RLS.
    db.add(PublicPassportIndex(public_id=public_id, passport_id=item.id, title=item.title,
        asset_sha256=item.asset_sha256, payload=payload_data, signature=signature, status="active"))
    # A second detached signature is produced by the configured provider (AWS KMS in
    # production) and the exact manifest is archived. Local mode is explicitly marked
    # non-immutable; it never claims S3 Object Lock semantics.
    from .foundation import attach_passport_signature_and_archive
    signed, archive = attach_passport_signature_and_archive(db, item, user)
    _audit(db, user, "trust_passport.issued", "trust_passport", item.id,
           {"document_id": doc.id, "asset_sha256": doc.sha256, "public_id": public_id,
            "signing_provider": signed.provider, "archive_provider": archive["provider"],
            "archive_immutable": bool(archive.get("immutable"))})
    db.commit(); db.refresh(item)
    base = PUBLIC_APP_URL or str(request.base_url).rstrip("/")
    return {"id": item.id, "public_id": item.public_id, "title": item.title, "status": item.status,
            "asset_sha256": item.asset_sha256, "issued_at": item.issued_at.isoformat(),
            "verification_url": f"{base}/verify/{item.public_id}", "signature_valid": True,
            "signing_provider": signed.provider, "signing_algorithm": signed.algorithm,
            "manifest_sha256": signed.manifest_sha256, "archive_provider": archive["provider"],
            "archive_immutable": bool(archive.get("immutable")), "archive_uri": archive["uri"]}


@router.get("/trust-passports")
def list_trust_passports(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(TrustPassport).where(TrustPassport.workspace_id == user.workspace_id).order_by(desc(TrustPassport.issued_at)).limit(100)).all()
    return [{"id": x.id, "public_id": x.public_id, "title": x.title, "status": x.status, "asset_sha256": x.asset_sha256, "issued_at": x.issued_at.isoformat()} for x in rows]


@router.post("/trust-passports/{passport_id}/revoke")
def revoke_trust_passport(passport_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("Brand Admin"))):
    item = db.scalar(select(TrustPassport).where(TrustPassport.id == passport_id, TrustPassport.workspace_id == user.workspace_id))
    if not item: raise HTTPException(404, "Passport not found.")
    item.status = "revoked"; item.revoked_at = utcnow()
    public_index = db.get(PublicPassportIndex, item.public_id)
    if public_index:
        public_index.status = "revoked"
        public_index.revoked_at = item.revoked_at
    _audit(db, user, "trust_passport.revoked", "trust_passport", item.id)
    db.commit(); return {"id": item.id, "status": item.status, "revoked_at": item.revoked_at.isoformat()}


@router.get("/public/trust-passports/{public_id}")
def verify_public_passport(public_id: str, db: Session = Depends(get_db)):
    # Only the public attestation index is queried here. Workspace records remain under RLS.
    item = db.get(PublicPassportIndex, public_id)
    if not item: raise HTTPException(404, "Trust Passport not found.")
    payload = item.payload or {}
    from .foundation import verify_passport_signature
    external_signature_valid = verify_passport_signature(db, public_id, payload)
    # Existing passports retain their original HMAC validation. Once a detached
    # provider signature exists, it becomes authoritative and cannot be bypassed by
    # falling back to the legacy signature if verification fails.
    signature_valid = external_signature_valid if external_signature_valid is not None else hmac.compare_digest(item.signature, _passport_payload_signature(payload))
    signature_record = db.get(PassportSignature, public_id)
    return {"verified": bool(signature_valid and item.status == "active"), "status": item.status,
            "title": item.title, "asset_sha256": item.asset_sha256, "issued_at": item.issued_at.isoformat(),
            "signed_manifest": payload,
            "verification": payload.get("verification", {}), "public_claims": payload.get("public_claims", []),
            "signature_valid": signature_valid,
            "signature_provider": signature_record.signing_provider if signature_record else "legacy_hmac",
            "signature": ({"provider": signature_record.signing_provider,
                "algorithm": signature_record.signing_algorithm,
                "key_id": signature_record.signing_key_id,
                "signature_b64": signature_record.signature_b64,
                "public_key_b64": signature_record.public_key_b64,
                "manifest_sha256": signature_record.manifest_sha256,
                "verification_method": "offline_public_key" if signature_record.public_key_b64 else signature_record.verification_method}
                if signature_record else None),
            "notice": "This verifies the integrity and recorded approval state of this ContexA passport. It does not independently prove every statement in the asset is true."}


@router.get("/trust-passports/{passport_id}/qr.svg")
def passport_qr(passport_id: str, request: FastAPIRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    item = db.scalar(select(TrustPassport).where(TrustPassport.id == passport_id, TrustPassport.workspace_id == user.workspace_id))
    if not item: raise HTTPException(404, "Passport not found.")
    try:
        import qrcode
        from qrcode.image.svg import SvgPathImage
        base = PUBLIC_APP_URL or str(request.base_url).rstrip("/")
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=6, border=2)
        qr.add_data(f"{base}/verify/{item.public_id}"); qr.make(fit=True)
        image = qr.make_image(image_factory=SvgPathImage)
        return Response(content=image.to_string(), media_type="image/svg+xml", headers={"Cache-Control": "private, max-age=3600"})
    except ImportError:
        raise HTTPException(503, "QR generation dependency is unavailable. Install qrcode[pil].")


# Multimodal inspection -----------------------------------------------------
def _rule_scan_text(text_content: str, rules: list[BrandRule]) -> list[dict[str, Any]]:
    findings = []
    for rule in rules:
        if not rule.is_active or not rule.pattern: continue
        try: matches = list(re.finditer(rule.pattern, text_content, re.I))[:30]
        except re.error: continue
        for match in matches:
            findings.append({"rule_code": rule.code, "title": rule.title, "severity": rule.severity,
                "matched_text": match.group(0)[:500], "start": match.start(), "end": match.end(),
                "status": "machine_signal_requires_review", "suggested_fix": rule.suggested_fix})
    return findings


@router.post("/multimodal/inspect", status_code=201)
async def inspect_multimodal_media(file: UploadFile = File(...), transcript_text: str = Form(default=""),
                                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _consume_media_inspection_limit(db, user)
    # Reuse the application-wide bounded upload reader so Trust OS inspection
    # obeys the same configured MAX_UPLOAD_MB limit as document ingestion.
    data = await read_upload_limited(file)
    name = Path(file.filename or "upload.bin").name
    suffix = Path(name).suffix.lower()
    mime = (file.content_type or "application/octet-stream").lower()
    allowed_images = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}
    allowed_docs = {".pdf", ".docx", ".pptx", ".txt", ".md"}
    allowed_video = {".mp4", ".mov", ".m4v", ".webm"}
    allowed_audio = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}
    if suffix not in allowed_images | allowed_docs | allowed_video | allowed_audio:
        raise HTTPException(422, "Supported formats: image, PDF/Office/text, MP4/MOV/WebM video, and MP3/WAV/M4A/AAC/OGG audio.")
    text_content = ""; meta: dict[str, Any] = {}; capability = {"ocr": "not_applicable", "video_frames": "not_applicable", "speech_to_text": "not_configured"}
    media_type = "image" if suffix in allowed_images else "document" if suffix in allowed_docs else "video" if suffix in allowed_video else "audio"
    if suffix in allowed_images | allowed_docs:
        try:
            _, text_content = parse_document(name, data)
            capability["ocr"] = "extracted" if text_content.strip() else "no_text_detected"
        except Exception as exc:
            capability["ocr"] = "unavailable"; meta["extraction_note"] = str(exc)[:500]
    elif media_type == "video":
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            with tempfile.TemporaryDirectory(prefix="contexa-media-") as temp_dir:
                input_path = Path(temp_dir) / f"input{suffix}"; input_path.write_bytes(data)
                frame_pattern = str(Path(temp_dir) / "frame-%03d.jpg")
                proc = subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-i", str(input_path), "-vf", "fps=1/5,scale=1280:-1", "-frames:v", "12", frame_pattern], capture_output=True, timeout=35)
                frames = sorted(Path(temp_dir).glob("frame-*.jpg"))
                frame_text = []
                for index, frame in enumerate(frames):
                    try:
                        _, extracted = parse_image(frame.read_bytes())
                        if extracted.strip(): frame_text.append(f"[frame {index + 1}, approx. {index * 5}s] {extracted.strip()}")
                    except Exception: pass
                text_content = "\n".join(frame_text)
                capability["video_frames"] = "extracted" if frames else "ffmpeg_error"
                capability["ocr"] = "extracted" if frame_text else "no_text_detected_or_tesseract_unavailable"
                meta["frames_sampled"] = len(frames); meta["ffmpeg_return_code"] = proc.returncode
        else:
            capability["video_frames"] = "ffmpeg_not_installed"
        meta["audio_track"] = "not_transcribed"; meta["note"] = "Video frames are sampled every five seconds. Audio transcription is not enabled in this deployment."
    else:
        ffprobe = shutil.which("ffprobe")
        if ffprobe:
            with tempfile.TemporaryDirectory(prefix="contexa-audio-") as temp_dir:
                path = Path(temp_dir) / f"audio{suffix}"; path.write_bytes(data)
                proc = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_name,sample_rate,channels", "-of", "json", str(path)], capture_output=True, timeout=12)
                try: meta["ffprobe"] = json.loads(proc.stdout.decode("utf-8", "replace"))
                except Exception: meta["ffprobe"] = {"status": "unavailable"}
        if transcript_text.strip():
            text_content = transcript_text.strip(); capability["speech_to_text"] = "user_supplied_transcript"
        else:
            capability["speech_to_text"] = "transcript_required"
        meta["note"] = "Audio metadata is inspected. Automatic speech recognition is not configured; supply a reviewed transcript for claim checks."
    rules = db.scalars(select(BrandRule).where(BrandRule.workspace_id == user.workspace_id)).all()
    findings = _rule_scan_text(text_content, rules) if text_content else []
    item = MediaInspection(workspace_id=user.workspace_id, filename=name, media_type=media_type,
        sha256=hashlib.sha256(data).hexdigest(), extracted_text=text_content[:100000], findings=findings,
        metadata_json={"mime_type": mime, "size_bytes": len(data), **meta}, capability_status=capability, created_by=user.id)
    db.add(item); db.flush()
    _audit(db, user, "multimodal.inspected", "media_inspection", item.id,
        {"filename": name, "media_type": media_type, "sha256": item.sha256, "finding_count": len(findings), "capabilities": capability})
    db.commit(); db.refresh(item)
    return {"id": item.id, "filename": name, "media_type": media_type, "sha256": item.sha256,
        "extracted_text": text_content[:100000], "findings": findings, "metadata": item.metadata_json,
        "capability_status": capability, "review_notice": "Automated extraction and pattern matches are screening signals. They do not confirm factual accuracy, visual authenticity or legal compliance."}


@router.get("/multimodal/inspections")
def list_multimodal_inspections(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(MediaInspection).where(MediaInspection.workspace_id == user.workspace_id).order_by(desc(MediaInspection.created_at)).limit(100)).all()
    return [{"id": x.id, "filename": x.filename, "media_type": x.media_type, "sha256": x.sha256,
             "finding_count": len(x.findings or []), "capability_status": x.capability_status, "created_at": x.created_at.isoformat()} for x in rows]


# Governed agent workflow ---------------------------------------------------
@router.post("/agents/runs", status_code=201)
def run_governance_agents(payload: AgentRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not payload.document_id and not payload.content_text:
        raise HTTPException(422, "Provide document_id or content_text.")
    doc = None
    if payload.document_id:
        doc = db.scalar(select(ContentDocument).where(ContentDocument.id == payload.document_id, ContentDocument.workspace_id == user.workspace_id))
        if not doc: raise HTTPException(404, "Document not found.")
    source_text = doc.content_text if doc else payload.content_text or ""
    steps: list[dict[str, Any]] = []
    claims = [s.strip() for s in re.split(r"(?<=[.!?])\s+", source_text) if re.search(r"\d|%|\b(best|first|fastest|guaranteed|certified|proven|number one)\b", s, re.I)][:80]
    steps.append({"agent": "Research Agent", "status": "completed", "summary": f"Extracted {len(claims)} potentially material claim sentence(s).", "evidence": "Document text or user-provided text"})
    rules = db.scalars(select(BrandRule).where(BrandRule.workspace_id == user.workspace_id, BrandRule.is_active.is_(True))).all()
    findings = _rule_scan_text(source_text, rules)
    steps.append({"agent": "Policy Agent", "status": "completed", "summary": f"Matched {len(findings)} deterministic rule pattern(s).", "finding_count": len(findings)})
    approved_facts = db.scalars(select(ApprovedFact).where(ApprovedFact.workspace_id == user.workspace_id, ApprovedFact.status == "approved")).all()
    fact_checks = []
    for claim in claims:
        matches = [f for f in approved_facts if f.canonical_value.strip() and f.canonical_value.lower() in claim.lower()]
        fact_checks.append({"claim": claim[:500], "status": "matched_approved_fact" if matches else "no_direct_fact_match", "fact_ids": [f.id for f in matches], "note": "No direct fact match is not proof that the claim is false; review evidence manually."})
    steps.append({"agent": "Evidence Agent", "status": "completed", "summary": f"Compared claims with {len(approved_facts)} currently approved fact(s).", "direct_matches": sum(1 for x in fact_checks if x["status"] == "matched_approved_fact")})
    weighted = sum(40 if x["severity"] == "critical" else 18 if x["severity"] == "warning" else 5 for x in findings)
    risk = min(100, weighted + (20 if any(x["status"] == "no_direct_fact_match" for x in fact_checks) else 0))
    steps.append({"agent": "Risk Agent", "status": "completed", "summary": f"Calculated a deterministic triage score of {risk}/100.", "method": "rule severity weights + review-needed signal; not a probability"})
    if doc and findings:
        critical = any(x["severity"] == "critical" for x in findings)
        task = ReviewTask(workspace_id=user.workspace_id, document_id=doc.id,
            assigned_role="SME / Legal" if critical else "Manager", reason="Governance agent workflow identified risk signals requiring a reviewer.",
            priority="urgent" if critical else "normal", status="open")
        db.add(task)
        steps.append({"agent": "Approval Agent", "status": "task_created", "summary": "Created a human review task; the workflow cannot approve or publish content."})
    else:
        steps.append({"agent": "Approval Agent", "status": "awaiting_human", "summary": "No autonomous publication or approval action is permitted."})
    outputs = {"claim_count": len(claims), "claims": claims, "rule_findings": findings, "fact_checks": fact_checks,
               "risk_triage_score": risk, "risk_score_type": "deterministic_triage_not_probability", "requires_human_review": True}
    run = AgentRun(workspace_id=user.workspace_id, document_id=doc.id if doc else None, objective=payload.objective,
        status="completed", steps=steps, outputs=outputs, requires_human_review=True, initiated_by=user.id, completed_at=utcnow())
    db.add(run); db.flush()
    from .foundation import record_agent_decision
    decision_input = {"document_id": doc.id if doc else None, "source_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        "objective": payload.objective, "active_rule_count": len(rules), "approved_fact_count": len(approved_facts)}
    record_agent_decision(db, run, user, decision_input, outputs)
    _audit(db, user, "agents.workflow_completed", "agent_run", run.id, {"document_id": run.document_id, "risk": risk, "steps": len(steps)})
    db.commit(); db.refresh(run)
    return {"id": run.id, "status": run.status, "objective": run.objective, "steps": run.steps, "outputs": run.outputs,
            "created_at": run.created_at.isoformat(), "note": "Governance agents execute deterministic, auditable checks. They do not have authority to approve or publish."}


@router.get("/agents/runs")
def list_agent_runs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(AgentRun).where(AgentRun.workspace_id == user.workspace_id).order_by(desc(AgentRun.created_at)).limit(100)).all()
    return [{"id": x.id, "document_id": x.document_id, "objective": x.objective, "status": x.status,
             "steps": x.steps, "outputs": x.outputs, "created_at": x.created_at.isoformat()} for x in rows]


# Brand Digital Twin -------------------------------------------------------
@router.post("/digital-twin/simulate", status_code=201)
def simulate_brand_twin(payload: TwinRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    docs = db.scalars(select(ContentDocument).where(ContentDocument.workspace_id == user.workspace_id)).all()
    facts = db.scalars(select(ApprovedFact).where(ApprovedFact.workspace_id == user.workspace_id, ApprovedFact.status == "approved")).all()
    impacted: dict[str, dict[str, Any]] = {}
    change_type = payload.scenario_type
    if change_type == "fact_change":
        for key, proposed in payload.proposed_changes.items():
            matched_facts = [f for f in facts if f.fact_key.lower() == str(key).lower()]
            for fact in matched_facts:
                old_value = fact.canonical_value
                for doc in docs:
                    if old_value and old_value.lower() in (doc.content_text or "").lower():
                        row = impacted.setdefault(doc.id, {"document_id": doc.id, "filename": doc.filename, "reasons": []})
                        row["reasons"].append({"fact_key": fact.fact_key, "old_value": old_value, "proposed_value": str(proposed)})
    elif change_type == "policy_change":
        pattern = str(payload.proposed_changes.get("pattern", ""))
        if not pattern: raise HTTPException(422, "policy_change requires proposed_changes.pattern.")
        try: compiled = re.compile(pattern, re.I)
        except re.error as exc: raise HTTPException(422, f"Invalid policy regex: {exc}")
        for doc in docs:
            matches = [m.group(0)[:200] for m in list(compiled.finditer(doc.content_text or ""))[:10]]
            if matches: impacted[doc.id] = {"document_id": doc.id, "filename": doc.filename, "reasons": [{"policy_pattern": pattern, "matches": matches}]}
    else:
        raise HTTPException(422, "scenario_type must be fact_change or policy_change.")
    report = {"documents_scanned": len(docs), "documents_potentially_affected": len(impacted),
              "affected_documents": list(impacted.values()), "proposed_changes": payload.proposed_changes,
              "recommendation": "Review the impacted assets and run the normal governance workflow before applying any real change.",
              "applied": False, "limitation": "Simulation uses stored extracted text and exact-value/pattern matching; it can miss paraphrases and OCR errors."}
    item = DigitalTwinScenario(workspace_id=user.workspace_id, name=payload.name, scenario_type=change_type,
        proposed_changes=payload.proposed_changes, impact_report=report, status="simulated", created_by=user.id)
    db.add(item); db.flush()
    _audit(db, user, "digital_twin.simulated", "digital_twin_scenario", item.id, {"type": change_type, "affected": len(impacted)})
    db.commit(); db.refresh(item)
    return {"id": item.id, "name": item.name, "scenario_type": item.scenario_type, "created_at": item.created_at.isoformat(), **report}


@router.get("/digital-twin/scenarios")
def list_twin_scenarios(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(DigitalTwinScenario).where(DigitalTwinScenario.workspace_id == user.workspace_id).order_by(desc(DigitalTwinScenario.created_at)).limit(100)).all()
    return [{"id": x.id, "name": x.name, "scenario_type": x.scenario_type, "impact_report": x.impact_report, "created_at": x.created_at.isoformat()} for x in rows]


# Indic language intelligence ---------------------------------------------
_NUMERIC_RE = re.compile(r"(?<![A-Za-z])(?:₹|Rs\.?\s*)?\d[\d,]*(?:\.\d+)?\s?(?:%|hours?|hrs?|days?|years?|वर्ष|दिन|घंटे|तास|दिवस)?", re.I)
_DISCLOSURES = {
    "ad": [
        "#ad", "advertisement", "sponsored", "paid partnership",
        "जाहिरात", "विज्ञापन", "प्रायोजित", "सशुल्क भागीदारी",
        "જાહેરાત", "પ્રાયોજિત", "ચૂકવેલ ભાગીદારી",
        "বিজ্ঞাপন", "স্পনসরড", "পেইড পার্টনারশিপ",
        "விளம்பரம்", "ஸ்பான்சர் செய்யப்பட்ட", "கட்டண கூட்டாண்மை",
        "ప్రకటన", "ప్రాయోజితం", "చెల్లింపు భాగస్వామ్యం",
        "ಜಾಹೀರಾತು", "ಪ್ರಾಯೋಜಿತ", "ಪಾವತಿಸಿದ ಪಾಲುದಾರಿಕೆ",
    ],
    "ai_generated": [
        "ai generated", "made with ai", "created using ai", "ai निर्मित", "एआय निर्मित", "एआई द्वारा निर्मित",
        "ai દ્વારા બનાવેલ", "એઆઈ દ્વારા બનાવેલ", "এআই দিয়ে তৈরি", "কৃত্রিমভাবে তৈরি",
        "ai மூலம் உருவாக்கப்பட்டது", "செயற்கையாக உருவாக்கப்பட்டது",
        "ai ద్వారా రూపొందించబడింది", "కృత్రిమంగా రూపొందించబడింది",
        "ai ಮೂಲಕ ರಚಿಸಲಾಗಿದೆ", "ಕೃತಕವಾಗಿ ರಚಿಸಲಾಗಿದೆ",
    ],
}
_LOCALIZED_TERMS = {
    "warranty": ["warranty", "वॉरंटी", "वारंटी", "हमी", "વોરંટી", "ખાતરી", "ওয়ারেন্টি", "গ্যারান্টি", "உத்தரவாதம்", "வாரண்டி", "వారంటీ", "హామీ", "ವಾರಂಟಿ", "ಖಾತರಿ"],
    "refund": ["refund", "रिफंड", "પરતફેર", "ফেরত", "பணத்தைத் திரும்பப் பெறுதல்", "వాపసు", "ಮರುಪಾವತಿ"],
    "free": ["free", "मुफ़्त", "मुफ्त", "મફત", "বিনামূল্যে", "இலவசம்", "ఉచితం", "ಉಚಿತ"],
    "guaranteed": ["guaranteed", "गारंटी", "ખાતરી", "গ্যারান্টিযুক্ত", "உத்தரவாதம்", "హామీ", "ಖಾತರಿ"],
    "certified": ["certified", "प्रमाणित", "પ્રમાણિત", "সনদপ্রাপ্ত", "சான்றளிக்கப்பட்ட", "ధృవీకరించబడిన", "ಪ್ರಮಾಣೀಕೃತ"],
}


def _normalize_unicode_digits(value: str) -> str:
    # Unicode decimal normalization covers Devanagari, Bengali, Gujarati, Tamil,
    # Telugu, Kannada and other Nd digit blocks without a per-script lookup table.
    return "".join(str(unicodedata.decimal(char)) if char.isdecimal() else char for char in value)


def _normalized_numbers(value: str) -> list[str]:
    normal = _normalize_unicode_digits(value).lower()
    return [re.sub(r"[^0-9.]", "", x) for x in _NUMERIC_RE.findall(normal)]


@router.post("/indic/review", status_code=201)
def review_localized_copy(payload: LanguageRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    checks: list[dict[str, Any]] = []
    source_nums = _normalized_numbers(payload.source_text); local_nums = _normalized_numbers(payload.localized_text)
    if source_nums != local_nums:
        checks.append({"code": "NUMERIC_PARITY", "severity": "high", "status": "mismatch", "source_values": source_nums, "localized_values": local_nums,
                       "message": "Numbers, percentages, currencies or duration values differ. Verify every value and unit manually."})
    else:
        checks.append({"code": "NUMERIC_PARITY", "severity": "pass", "status": "matched", "message": "Extracted numeric tokens match. Unit meaning and context still require review."})
    lower_source = payload.source_text.lower(); lower_local = payload.localized_text.lower()
    for category, words in _DISCLOSURES.items():
        source_has = any(word in lower_source for word in words)
        local_has = any(word in lower_local for word in words)
        if source_has and not local_has:
            checks.append({"code": f"DISCLOSURE_{category.upper()}", "severity": "high", "status": "missing_localized_disclosure",
                           "message": f"A {category.replace('_', ' ')} disclosure appears in the source but no configured localized equivalent was detected."})
    terms = [w for w in ["warranty", "refund", "free", "guaranteed", "certified", "clinically tested"] if w in lower_source]
    for term in terms:
        variants = _LOCALIZED_TERMS.get(term, [term])
        if not any(variant.casefold() in lower_local for variant in variants):
            checks.append({"code": "KEY_TERM_REVIEW", "severity": "medium", "status": "term_not_found", "term": term,
                           "message": f"No configured localized variant for source term '{term}' was found. This may be a correct translation; verify semantics with a native reviewer."})
    if not checks: checks.append({"code": "BASIC_PARITY", "severity": "info", "status": "no_machine_signal", "message": "No configured numeric or disclosure mismatch detected."})
    item = LanguageReview(workspace_id=user.workspace_id, language=payload.language, source_text=payload.source_text,
        localized_text=payload.localized_text, checks=checks, status="human_review_required", created_by=user.id)
    db.add(item); db.flush()
    _audit(db, user, "indic.language_reviewed", "language_review", item.id, {"language": payload.language, "checks": len(checks)})
    db.commit(); db.refresh(item)
    return {"id": item.id, "language": item.language, "checks": checks, "status": item.status,
            "limitations": ["This is not a machine translation or semantic-equivalence certification.", "Marathi/Hindi grammar, idioms, cultural meaning and legal terminology require a qualified reviewer.", "Digit normalization is supported for Devanagari numerals; additional writing systems may need custom normalization."]}


@router.get("/indic/reviews")
def list_language_reviews(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(LanguageReview).where(LanguageReview.workspace_id == user.workspace_id).order_by(desc(LanguageReview.created_at)).limit(100)).all()
    return [{"id": x.id, "language": x.language, "checks": x.checks, "status": x.status, "created_at": x.created_at.isoformat()} for x in rows]


# Regulatory intelligence ---------------------------------------------------
REGULATORY_SEEDS = [
    {"requirement_code": "IN-ASCI-TRUTH-001", "jurisdiction": "India", "industry": "Advertising", "title": "Objective advertising claims need substantiation", "authority": "Advertising Standards Council of India", "source_url": "https://www.ascionline.in/the-asci-code/", "requirement_summary": "Objectively ascertainable descriptions, claims and comparisons should be capable of substantiation. Advertisers may be asked to produce supporting evidence.", "trigger_terms": ["best", "number one", "fastest", "guaranteed", "clinically proven", "%", "increase", "save", "reduce"], "required_terms": ["study", "report", "source", "data", "evidence", "according to"], "effective_from": None, "source_version": "Seeded reference summary; source not automatically fetched; legal review required"},
    {"requirement_code": "IN-ASCI-INFLUENCER-002", "jurisdiction": "India", "industry": "Digital advertising", "title": "Prominent influencer material-connection disclosure", "authority": "Advertising Standards Council of India", "source_url": "https://www.ascionline.in/the-asci-code-guidelines/", "requirement_summary": "Where a material connection exists, digital influencer advertising should carry a clear, upfront and prominent advertisement disclosure. Applicability depends on the relationship and communication context.", "trigger_terms": ["influencer", "creator partnership", "brand collaboration", "gifted", "free product", "paid partnership", "ambassador"], "required_terms": ["#ad", "advertisement", "sponsored", "paid partnership", "जाहिरात", "विज्ञापन"], "effective_from": "2023-09-01", "source_version": "Seeded reference summary; source not automatically fetched; legal review required"},
    {"requirement_code": "IN-DPDP-2025-NOTICE", "jurisdiction": "India", "industry": "Personal data", "title": "Personal data notice and processing transparency", "authority": "Ministry of Electronics and Information Technology", "source_url": "https://www.meity.gov.in/documents/act-and-policies/digital-personal-data-protection-rules-2025-gDOxUjMtQWa?pageTitle=Digital-Personal-Data-Protection-Rules-2025", "requirement_summary": "The DPDP Act, 2023 and DPDP Rules, 2025 establish obligations for processing digital personal data. Review applicable notice, purpose, consent/other permitted grounds, rights and security requirements against commencement and applicability provisions.", "trigger_terms": ["collect your email", "personal data", "phone number", "location data", "health information", "user data", "we collect"], "required_terms": ["privacy policy", "personal data", "purpose", "consent", "notice", "data protection"], "effective_from": "2025-11-14", "source_version": "Seeded reference summary; commencement schedule and applicability require review"},
    {"requirement_code": "EU-AIA-ARTICLE50", "jurisdiction": "European Union", "industry": "AI-generated content", "title": "AI content and deepfake transparency review", "authority": "European Commission / EU AI Act", "source_url": "https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-50", "requirement_summary": "Article 50 sets transparency obligations for specified AI systems and certain AI-generated/manipulated content. Applicability and exceptions depend on system role, content type and context.", "trigger_terms": ["deepfake", "ai-generated", "generated by ai", "synthetic media", "voice clone", "ai avatar"], "required_terms": ["ai generated", "created using ai", "synthetic", "artificially generated", "manipulated"], "effective_from": "2026-08-02", "source_version": "Seeded reference summary; source not automatically fetched; applicability review required"},
    {"requirement_code": "US-FTC-ENDORSEMENT", "jurisdiction": "United States", "industry": "Advertising and endorsements", "title": "Endorsement and material-connection disclosure review", "authority": "Federal Trade Commission", "source_url": "https://www.ftc.gov/news-events/topics/truth-advertising/advertisement-endorsements", "requirement_summary": "Endorsements should be truthful and not misleading. Material connections that may affect how consumers evaluate an endorsement should be disclosed clearly.", "trigger_terms": ["testimonial", "influencer", "endorsement", "review", "ambassador", "gifted", "sponsored"], "required_terms": ["sponsored", "paid partnership", "advertisement", "#ad", "gifted"], "effective_from": "2023-06-29", "source_version": "Seeded reference summary; source not automatically fetched; legal review required"},
]


def _ensure_regulatory_seeds(db: Session, user: User) -> None:
    for seed in REGULATORY_SEEDS:
        exists = db.scalar(select(RegulatoryRequirement.id).where(RegulatoryRequirement.workspace_id == user.workspace_id, RegulatoryRequirement.requirement_code == seed["requirement_code"]))
        if not exists:
            db.add(RegulatoryRequirement(workspace_id=user.workspace_id, **seed, source_checked_at=None))
    db.flush()


def _regulatory_out(x: RegulatoryRequirement) -> dict[str, Any]:
    return {"id": x.id, "requirement_code": x.requirement_code, "jurisdiction": x.jurisdiction, "industry": x.industry,
            "title": x.title, "authority": x.authority, "source_url": x.source_url, "requirement_summary": x.requirement_summary,
            "trigger_terms": x.trigger_terms, "required_terms": x.required_terms, "effective_from": x.effective_from,
            "source_checked_at": x.source_checked_at.isoformat() if x.source_checked_at else None, "source_version": x.source_version, "status": x.status}


@router.get("/regulatory/requirements")
def list_regulatory_requirements(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _ensure_regulatory_seeds(db, user); db.commit()
    rows = db.scalars(select(RegulatoryRequirement).where(RegulatoryRequirement.workspace_id == user.workspace_id, RegulatoryRequirement.status == "active").order_by(RegulatoryRequirement.jurisdiction, RegulatoryRequirement.requirement_code)).all()
    return [_regulatory_out(x) for x in rows]


@router.post("/regulatory/requirements", status_code=201)
def create_regulatory_requirement(payload: RegulatoryCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("SME / Legal", "Brand Admin"))):
    if urlparse(payload.source_url).scheme != "https": raise HTTPException(422, "Regulatory source URL must use HTTPS.")
    exists = db.scalar(select(RegulatoryRequirement.id).where(RegulatoryRequirement.workspace_id == user.workspace_id, RegulatoryRequirement.requirement_code == payload.requirement_code))
    if exists: raise HTTPException(409, "Requirement code already exists in this workspace.")
    item = RegulatoryRequirement(workspace_id=user.workspace_id, **payload.model_dump(), source_checked_at=None, status="draft")
    db.add(item); db.flush()
    _audit(db, user, "regulatory.requirement_created", "regulatory_requirement", item.id, {"code": item.requirement_code})
    db.commit(); db.refresh(item); return _regulatory_out(item)


@router.post("/regulatory/assess")
def assess_regulatory_content(payload: RegulatoryAssessmentRequest,
                             db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    document_id, content_text = payload.document_id, payload.content_text
    if not document_id and not content_text: raise HTTPException(422, "Provide document_id or content_text.")
    doc = None
    if document_id:
        doc = db.scalar(select(ContentDocument).where(ContentDocument.id == document_id, ContentDocument.workspace_id == user.workspace_id))
        if not doc: raise HTTPException(404, "Document not found.")
    body = doc.content_text if doc else content_text or ""
    _ensure_regulatory_seeds(db, user)
    requirements = db.scalars(select(RegulatoryRequirement).where(RegulatoryRequirement.workspace_id == user.workspace_id, RegulatoryRequirement.status == "active")).all()
    assessment_id = new_id(); findings = []
    for req in requirements:
        lower = body.lower()
        triggers = [term for term in req.trigger_terms if term.lower() in lower]
        if not triggers: result = "not_triggered"; missing = []
        else:
            required = [term for term in req.required_terms if term.lower() in lower]
            missing = [] if required else req.required_terms[:]
            result = "potential_gap" if missing else "review_required"
        details = {"trigger_hits": triggers[:20], "required_indicator_hits": [t for t in req.required_terms if t.lower() in lower][:20],
                   "missing_indicators": missing, "summary": req.requirement_summary, "authority": req.authority,
                   "source_url": req.source_url, "source_version": req.source_version,
                   "disclaimer": "Keyword screening only; applicability, exceptions, legal interpretation and compliance require qualified review."}
        row = RegulatoryAssessment(workspace_id=user.workspace_id, document_id=doc.id if doc else None,
            assessment_id=assessment_id, jurisdiction=req.jurisdiction, requirement_code=req.requirement_code,
            result=result, details=details, created_by=user.id)
        db.add(row); findings.append({"requirement_code": req.requirement_code, "jurisdiction": req.jurisdiction, "title": req.title, "result": result, **details})
    _audit(db, user, "regulatory.assessment_run", "regulatory_assessment", assessment_id, {"document_id": doc.id if doc else None, "requirements": len(requirements)})
    db.commit()
    return {"assessment_id": assessment_id, "document_id": doc.id if doc else None, "requirements_checked": len(requirements), "findings": findings,
            "notice": "This is a screening workflow, not legal advice, legal certification or a determination of compliance."}


@router.get("/regulatory/assessments")
def list_regulatory_assessments(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(RegulatoryAssessment).where(RegulatoryAssessment.workspace_id == user.workspace_id).order_by(desc(RegulatoryAssessment.created_at)).limit(100)).all()
    return [{"assessment_id": x.assessment_id, "jurisdiction": x.jurisdiction, "requirement_code": x.requirement_code, "result": x.result, "details": x.details, "document_id": x.document_id, "created_at": x.created_at.isoformat()} for x in rows]


# Brand incident command centre --------------------------------------------
@router.get("/incidents")
def list_incidents(status: str | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    q = select(BrandIncident).where(BrandIncident.workspace_id == user.workspace_id)
    if status: q = q.where(BrandIncident.status == status)
    return [_incident_out(x) for x in db.scalars(q.order_by(desc(BrandIncident.updated_at)).limit(200)).all()]


@router.post("/incidents", status_code=201)
def create_incident(payload: IncidentCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("Manager", "SME / Legal", "Brand Admin"))):
    severity = payload.severity.lower()
    if severity not in {"low", "medium", "high", "critical"}: raise HTTPException(422, "Invalid severity.")
    allowed_ids = set(db.scalars(select(ContentDocument.id).where(ContentDocument.workspace_id == user.workspace_id, ContentDocument.id.in_(payload.affected_document_ids or ["__none__"]))).all())
    if allowed_ids != set(payload.affected_document_ids): raise HTTPException(422, "One or more affected documents are outside this workspace or do not exist.")
    item = _new_incident(db, user, payload.title, payload.description, severity, payload.source_type, payload.source_id, payload.affected_document_ids)
    _audit(db, user, "incident.created", "brand_incident", item.id, {"severity": severity})
    db.commit(); db.refresh(item); return _incident_out(item)


@router.patch("/incidents/{incident_id}")
def update_incident(incident_id: str, payload: IncidentUpdate, db: Session = Depends(get_db), user: User = Depends(require_roles("Manager", "SME / Legal", "Brand Admin"))):
    item = db.scalar(select(BrandIncident).where(BrandIncident.id == incident_id, BrandIncident.workspace_id == user.workspace_id))
    if not item: raise HTTPException(404, "Incident not found.")
    next_status = payload.status.lower()
    if next_status not in {"open", "acknowledged", "investigating", "resolved"}: raise HTTPException(422, "Invalid incident status.")
    old_status = item.status; item.status = next_status; item.updated_at = utcnow()
    if payload.resolution: item.resolution = payload.resolution
    if next_status == "resolved":
        if not (payload.resolution or item.resolution): raise HTTPException(422, "A resolution note is required to close an incident.")
        item.resolved_at = utcnow()
    else: item.resolved_at = None
    timeline = list(item.timeline or []); timeline.append({"at": _now().isoformat(), "action": f"status:{old_status}->{next_status}", "actor": user.name, "note": payload.note or payload.resolution or ""})
    item.timeline = timeline[-100:]
    _audit(db, user, "incident.updated", "brand_incident", item.id, {"from": old_status, "to": next_status})
    db.commit(); db.refresh(item); return _incident_out(item)
