"""Round 4 backend features: notifications, comments, compliance history, search and observability.

Everything here is real, workspace-scoped data derived from the existing tables. Nothing is mocked:

* ``notifications``        in-app inbox, created by review routing, @mentions, publication
* ``comments``             threaded discussion on documents/findings with @email mentions
* ``compliance_snapshots`` one row per workspace per UTC day, written on every state change
* ``/api/search``          server-side search across documents, rules, findings and comments
* request-id middleware, structured access log, ``/api/health/live|ready`` and ``/api/metrics``

Every query filters by ``workspace_id`` (and PostgreSQL RLS enforces it again at the database).
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import secrets
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, or_, select, text
from sqlalchemy.orm import Session

from .database import engine, get_db
from .models import (AuditEvent, BrandRule, Comment, ComplianceSnapshot, ContentDocument, Notification,
                     ReviewFinding, ReviewTask, User, utcnow)
from .security import get_current_user, require_roles

logger = logging.getLogger("contexa.ops")
router = APIRouter(prefix="/api", tags=["collaboration"])

MANAGERS = ("Manager", "SME / Legal", "Brand Admin")
MENTION_RE = re.compile(r"@([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})")
METRICS_TOKEN = os.getenv("METRICS_TOKEN", "")
APP_VERSION = "1.1.0"
_STARTED_AT = time.time()


# ---------------------------------------------------------------------------
# Shared helpers (also imported by main.py hooks)
# ---------------------------------------------------------------------------

def _audit(db: Session, user: User, action: str, entity_type: str, entity_id: str, detail: dict[str, Any] | None = None):
    from .main import _audit as main_audit  # late import: main imports this module
    return main_audit(db, user, action, entity_type, entity_id, detail)


def notify(db: Session, workspace_id: str, user_ids: list[str], kind: str, title: str, body: str = "",
           entity_type: str | None = None, entity_id: str | None = None, actor_id: str | None = None) -> int:
    """Create one notification per distinct active workspace member (never for the actor)."""
    recipients = {uid for uid in user_ids if uid and uid != actor_id}
    if not recipients:
        return 0
    members = db.scalars(select(User.id).where(User.workspace_id == workspace_id,
                                               User.is_active.is_(True), User.id.in_(recipients))).all()
    for uid in members:
        db.add(Notification(workspace_id=workspace_id, user_id=uid, kind=kind, title=title[:200],
                            body=body[:2000], entity_type=entity_type, entity_id=entity_id, actor_id=actor_id))
    return len(members)


def workspace_admin_ids(db: Session, workspace_id: str) -> list[str]:
    return list(db.scalars(select(User.id).where(User.workspace_id == workspace_id,
                                                 User.role == "Brand Admin", User.is_active.is_(True))).all())


def record_snapshot(db: Session, workspace_id: str) -> ComplianceSnapshot | None:
    """Upsert today's posture row. Failure must never break the business operation."""
    try:
        with db.begin_nested():
            docs = db.scalars(select(ContentDocument).where(ContentDocument.workspace_id == workspace_id)).all()
            open_rows = db.execute(select(ReviewFinding.severity, func.count()).join(
                ContentDocument, ContentDocument.id == ReviewFinding.content_id).where(
                ContentDocument.workspace_id == workspace_id, ReviewFinding.status == "open"
            ).group_by(ReviewFinding.severity)).all()
            by_sev = {sev: n for sev, n in open_rows}
            open_tasks = db.scalar(select(func.count()).select_from(ReviewTask).where(
                ReviewTask.workspace_id == workspace_id, ReviewTask.status != "completed")) or 0
            active_rules = db.scalar(select(func.count()).select_from(BrandRule).where(
                BrandRule.workspace_id == workspace_id, BrandRule.is_active.is_(True))) or 0
            today = datetime.now(timezone.utc).date().isoformat()
            snap = db.scalar(select(ComplianceSnapshot).where(
                ComplianceSnapshot.workspace_id == workspace_id, ComplianceSnapshot.snapshot_date == today))
            if not snap:
                snap = ComplianceSnapshot(workspace_id=workspace_id, snapshot_date=today)
                db.add(snap)
            snap.integrity_score = int(round(sum(d.compliance_score for d in docs) / len(docs))) if docs else 100
            snap.total_documents = len(docs)
            snap.publish_ready = sum(1 for d in docs if d.status == "PUBLISH_READY")
            snap.open_findings = sum(by_sev.values())
            snap.critical_findings = by_sev.get("critical", 0)
            snap.warning_findings = by_sev.get("warning", 0)
            snap.open_tasks = open_tasks
            snap.active_rules = active_rules
            snap.updated_at = utcnow()
            db.flush()
            return snap
    except Exception:  # pragma: no cover - defensive
        logger.exception("Could not record compliance snapshot for %s", workspace_id)
        return None


def _doc_or_404(db: Session, user: User, doc_id: str) -> ContentDocument:
    doc = db.get(ContentDocument, doc_id)
    if not doc or doc.workspace_id != user.workspace_id:
        raise HTTPException(status_code=404, detail="Document not found.")
    return doc


# ---------------------------------------------------------------------------
# Public sign-in capabilities: lets the login screen show only what really works
# ---------------------------------------------------------------------------

@router.get("/auth/config")
def auth_config() -> dict[str, Any]:
    """Public, non-sensitive description of which sign-in options are usable on this server."""
    from . import config
    from .main import _smtp_ready
    local = config.AUTH_MODE in {"local", "hybrid"}
    dev = config.APP_ENV.lower() in {"development", "demo", "test"}
    smtp = _smtp_ready()
    if local and smtp:
        delivery = "email"
    elif local and dev:
        delivery = "development_link"  # reset link is returned to the browser instead of emailed
    else:
        delivery = "none"
    return {
        "auth_mode": config.AUTH_MODE,
        "local_login": local,
        "signup_open": bool(local and config.ALLOW_SIGNUP),
        "email_verification_required": bool(config.EMAIL_VERIFICATION_REQUIRED),
        "password_recovery": delivery != "none",
        "recovery_delivery": delivery,
        "demo_accounts": dev,
    }


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def _notification_out(n: Notification) -> dict[str, Any]:
    return {"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "entity_type": n.entity_type,
            "entity_id": n.entity_id, "actor_id": n.actor_id, "read": n.read_at is not None,
            "read_at": n.read_at, "created_at": n.created_at}


@router.get("/notifications")
def list_notifications(unread_only: bool = False, limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0),
                       db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    base = select(Notification).where(Notification.workspace_id == user.workspace_id, Notification.user_id == user.id)
    if unread_only:
        base = base.where(Notification.read_at.is_(None))
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(base.order_by(desc(Notification.created_at)).limit(limit).offset(offset)).all()
    unread = db.scalar(select(func.count()).select_from(Notification).where(
        Notification.workspace_id == user.workspace_id, Notification.user_id == user.id, Notification.read_at.is_(None))) or 0
    return {"items": [_notification_out(n) for n in rows], "total": total, "unread_count": unread,
            "limit": limit, "offset": offset}


@router.get("/notifications/unread-count")
def unread_count(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"unread_count": db.scalar(select(func.count()).select_from(Notification).where(
        Notification.workspace_id == user.workspace_id, Notification.user_id == user.id,
        Notification.read_at.is_(None))) or 0}


@router.post("/notifications/read-all")
def mark_all_read(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(Notification).where(Notification.workspace_id == user.workspace_id,
        Notification.user_id == user.id, Notification.read_at.is_(None))).all()
    now = utcnow()
    for n in rows:
        n.read_at = now
    db.commit()
    return {"marked_read": len(rows), "unread_count": 0}


@router.post("/notifications/{notification_id}/read")
def mark_read(notification_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    n = db.get(Notification, notification_id)
    if not n or n.workspace_id != user.workspace_id or n.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notification not found.")
    n.read_at = n.read_at or utcnow()
    db.commit()
    return _notification_out(n)


# ---------------------------------------------------------------------------
# Comments (threaded, with @email mentions)
# ---------------------------------------------------------------------------

class CommentCreate(BaseModel):
    entity_type: Literal["document", "finding"]
    entity_id: str = Field(min_length=1, max_length=36)
    body: str = Field(min_length=1, max_length=4000)
    parent_id: str | None = None


class CommentUpdate(BaseModel):
    body: str | None = Field(default=None, min_length=1, max_length=4000)
    resolved: bool | None = None


def _comment_out(c: Comment) -> dict[str, Any]:
    return {"id": c.id, "entity_type": c.entity_type, "entity_id": c.entity_id, "parent_id": c.parent_id,
            "author_id": c.author_id, "author_name": c.author_name,
            "body": "[deleted]" if c.is_deleted else c.body, "mentions": [] if c.is_deleted else c.mentions,
            "resolved": c.resolved, "is_deleted": c.is_deleted, "created_at": c.created_at, "edited_at": c.edited_at}


def _resolve_entity_document(db: Session, user: User, entity_type: str, entity_id: str) -> ContentDocument:
    if entity_type == "document":
        return _doc_or_404(db, user, entity_id)
    finding = db.get(ReviewFinding, entity_id)
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found.")
    return _doc_or_404(db, user, finding.content_id)


def _parse_mentions(db: Session, workspace_id: str, body: str) -> list[User]:
    emails = {m.lower() for m in MENTION_RE.findall(body)}
    if not emails:
        return []
    return list(db.scalars(select(User).where(User.workspace_id == workspace_id,
                                              User.is_active.is_(True), User.email.in_(emails))).all())


@router.get("/comments")
def list_comments(entity_type: Literal["document", "finding"], entity_id: str,
                  db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _resolve_entity_document(db, user, entity_type, entity_id)
    rows = db.scalars(select(Comment).where(Comment.workspace_id == user.workspace_id,
        Comment.entity_type == entity_type, Comment.entity_id == entity_id).order_by(Comment.created_at)).all()
    by_parent: dict[str | None, list[Comment]] = defaultdict(list)
    for c in rows:
        by_parent[c.parent_id].append(c)
    threads = []
    for root in by_parent[None]:
        item = _comment_out(root)
        item["replies"] = [_comment_out(r) for r in by_parent.get(root.id, [])]
        threads.append(item)
    return {"threads": threads, "total": len(rows), "open_threads": sum(1 for t in threads if not t["resolved"])}


@router.post("/comments", status_code=201)
def create_comment(payload: CommentCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = _resolve_entity_document(db, user, payload.entity_type, payload.entity_id)
    if payload.parent_id:
        parent = db.get(Comment, payload.parent_id)
        if (not parent or parent.workspace_id != user.workspace_id or parent.entity_id != payload.entity_id
                or parent.entity_type != payload.entity_type):
            raise HTTPException(status_code=404, detail="The comment you are replying to was not found.")
        if parent.parent_id:
            raise HTTPException(status_code=422, detail="Replies can only be one level deep. Reply to the top-level comment.")
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="Write a comment before posting.")
    mentioned = _parse_mentions(db, user.workspace_id, body)
    comment = Comment(workspace_id=user.workspace_id, entity_type=payload.entity_type, entity_id=payload.entity_id,
                      parent_id=payload.parent_id, author_id=user.id, author_name=user.name, body=body,
                      mentions=[m.id for m in mentioned])
    db.add(comment); db.flush()
    notify(db, user.workspace_id, [m.id for m in mentioned], "mention", f"{user.name} mentioned you on {doc.filename}",
           body[:300], "document", doc.id, user.id)
    # Let the document owner know about new discussion on their upload.
    notify(db, user.workspace_id, [doc.created_by], "comment", f"New comment on {doc.filename}", body[:300],
           "document", doc.id, user.id) if doc.created_by not in {m.id for m in mentioned} else None
    _audit(db, user, "comment.created", payload.entity_type, payload.entity_id,
           {"comment_id": comment.id, "document_id": doc.id, "mentions": len(mentioned)})
    db.commit(); db.refresh(comment)
    return _comment_out(comment)


@router.patch("/comments/{comment_id}")
def update_comment(comment_id: str, payload: CommentUpdate, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    c = db.get(Comment, comment_id)
    if not c or c.workspace_id != user.workspace_id or c.is_deleted:
        raise HTTPException(status_code=404, detail="Comment not found.")
    if payload.body is not None:
        if c.author_id != user.id:
            raise HTTPException(status_code=403, detail="Only the author can edit a comment.")
        c.body = payload.body.strip(); c.edited_at = utcnow()
        c.mentions = [m.id for m in _parse_mentions(db, user.workspace_id, c.body)]
    if payload.resolved is not None:
        if c.parent_id:
            raise HTTPException(status_code=422, detail="Resolve the top-level comment, not a reply.")
        if c.author_id != user.id and user.role not in MANAGERS:
            raise HTTPException(status_code=403, detail="Only the author or a reviewer can resolve this thread.")
        c.resolved = payload.resolved
    _audit(db, user, "comment.updated", c.entity_type, c.entity_id, {"comment_id": c.id, "resolved": c.resolved})
    db.commit(); db.refresh(c)
    return _comment_out(c)


@router.delete("/comments/{comment_id}", status_code=204)
def delete_comment(comment_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = db.get(Comment, comment_id)
    if not c or c.workspace_id != user.workspace_id or c.is_deleted:
        raise HTTPException(status_code=404, detail="Comment not found.")
    if c.author_id != user.id and user.role != "Brand Admin":
        raise HTTPException(status_code=403, detail="Only the author or a Brand Admin can delete a comment.")
    c.is_deleted = True
    _audit(db, user, "comment.deleted", c.entity_type, c.entity_id, {"comment_id": c.id})
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Per-document activity timeline (from the tamper-evident audit chain)
# ---------------------------------------------------------------------------

@router.get("/documents/{doc_id}/activity")
def document_activity(doc_id: str, limit: int = Query(50, ge=1, le=200),
                      db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = _doc_or_404(db, user, doc_id)
    finding_ids = set(db.scalars(select(ReviewFinding.id).where(ReviewFinding.content_id == doc.id)).all())
    events = db.scalars(select(AuditEvent).where(AuditEvent.workspace_id == user.workspace_id)
                        .order_by(desc(AuditEvent.created_at)).limit(1500)).all()
    out = []
    for e in events:
        detail = e.detail or {}
        if e.entity_id == doc.id or e.entity_id in finding_ids or detail.get("document_id") == doc.id:
            out.append({"id": e.id, "action": e.action, "actor_name": e.actor_name, "entity_type": e.entity_type,
                        "entity_id": e.entity_id, "detail": detail, "created_at": e.created_at,
                        "event_hash": e.event_hash})
        if len(out) >= limit:
            break
    return {"document_id": doc.id, "filename": doc.filename, "events": out}


# ---------------------------------------------------------------------------
# Compliance history
# ---------------------------------------------------------------------------

def _snapshot_out(s: ComplianceSnapshot) -> dict[str, Any]:
    return {"date": s.snapshot_date, "integrity_score": s.integrity_score, "total_documents": s.total_documents,
            "publish_ready": s.publish_ready, "open_findings": s.open_findings,
            "critical_findings": s.critical_findings, "warning_findings": s.warning_findings,
            "open_tasks": s.open_tasks, "active_rules": s.active_rules}


@router.get("/analytics/trend")
def analytics_trend(days: int = Query(30, ge=1, le=365), format: Literal["json", "csv"] = "json",
                    db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    record_snapshot(db, user.workspace_id); db.commit()
    since = (datetime.now(timezone.utc).date() - timedelta(days=days - 1)).isoformat()
    rows = db.scalars(select(ComplianceSnapshot).where(ComplianceSnapshot.workspace_id == user.workspace_id,
        ComplianceSnapshot.snapshot_date >= since).order_by(ComplianceSnapshot.snapshot_date)).all()
    series = [_snapshot_out(r) for r in rows]
    if format == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(series[0].keys()) if series else ["date"])
        writer.writeheader(); writer.writerows(series)
        return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                                 headers={"Content-Disposition": 'attachment; filename="contexa-compliance-trend.csv"'})
    first, last = (series[0], series[-1]) if series else (None, None)
    summary = {"points": len(series),
               "score_change": (last["integrity_score"] - first["integrity_score"]) if first and last and first is not last else 0,
               "critical_change": (last["critical_findings"] - first["critical_findings"]) if first and last and first is not last else 0,
               "best_score": max((s["integrity_score"] for s in series), default=None),
               "lowest_score": min((s["integrity_score"] for s in series), default=None)}
    return {"days": days, "series": series, "summary": summary}


@router.post("/analytics/snapshot")
def force_snapshot(db: Session = Depends(get_db), user: User = Depends(require_roles(*MANAGERS))):
    snap = record_snapshot(db, user.workspace_id)
    db.commit()
    if not snap:
        raise HTTPException(status_code=500, detail="Snapshot could not be recorded.")
    return _snapshot_out(snap)


@router.get("/analytics/workload")
def analytics_workload(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Open review load per reviewer and overdue counts, from real review_tasks."""
    tasks = db.scalars(select(ReviewTask).where(ReviewTask.workspace_id == user.workspace_id,
                                                ReviewTask.status != "completed")).all()
    now = utcnow()
    names = {u.id: u.name for u in db.scalars(select(User).where(User.workspace_id == user.workspace_id)).all()}
    per: dict[str, dict[str, Any]] = {}
    overdue = 0
    for t in tasks:
        key = t.assigned_to or f"role:{t.assigned_role}"
        row = per.setdefault(key, {"assignee": names.get(t.assigned_to, f"Unassigned ({t.assigned_role})"),
                                   "open": 0, "overdue": 0, "critical": 0})
        row["open"] += 1
        due = t.due_at.replace(tzinfo=timezone.utc) if t.due_at and t.due_at.tzinfo is None else t.due_at
        if due and due < now:
            row["overdue"] += 1; overdue += 1
        if t.priority == "critical":
            row["critical"] += 1
    return {"open_tasks": len(tasks), "overdue_tasks": overdue,
            "by_assignee": sorted(per.values(), key=lambda r: (-r["overdue"], -r["open"]))}


# ---------------------------------------------------------------------------
# Server-side search
# ---------------------------------------------------------------------------

def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


@router.get("/search")
def search(q: str = Query(min_length=2, max_length=120), limit: int = Query(8, ge=1, le=25),
           db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    term = q.strip()
    if len(term) < 2:
        raise HTTPException(status_code=422, detail="Type at least 2 characters to search.")
    pattern = _like(term)
    ws = user.workspace_id
    docs = db.scalars(select(ContentDocument).where(ContentDocument.workspace_id == ws,
        ContentDocument.filename.ilike(pattern, escape="\\")).order_by(desc(ContentDocument.updated_at)).limit(limit)).all()
    rules = db.scalars(select(BrandRule).where(BrandRule.workspace_id == ws, or_(
        BrandRule.title.ilike(pattern, escape="\\"), BrandRule.code.ilike(pattern, escape="\\"),
        BrandRule.rule_clause.ilike(pattern, escape="\\"))).limit(limit)).all()
    findings = db.execute(select(ReviewFinding, ContentDocument.filename).join(
        ContentDocument, ContentDocument.id == ReviewFinding.content_id).where(
        ContentDocument.workspace_id == ws, or_(ReviewFinding.flagged_text.ilike(pattern, escape="\\"),
        ReviewFinding.reasoning.ilike(pattern, escape="\\"))).limit(limit)).all()
    comments = db.scalars(select(Comment).where(Comment.workspace_id == ws, Comment.is_deleted.is_(False),
        Comment.body.ilike(pattern, escape="\\")).order_by(desc(Comment.created_at)).limit(limit)).all()
    results = {
        "documents": [{"id": d.id, "filename": d.filename, "status": d.status, "score": d.compliance_score} for d in docs],
        "rules": [{"id": r.id, "code": r.code, "title": r.title, "category": r.category, "is_active": r.is_active} for r in rules],
        "findings": [{"id": f.id, "document_id": f.content_id, "filename": name, "severity": f.severity,
                      "status": f.status, "flagged_text": (f.flagged_text or "")[:200]} for f, name in findings],
        "comments": [{"id": c.id, "entity_type": c.entity_type, "entity_id": c.entity_id,
                      "author_name": c.author_name, "body": c.body[:200]} for c in comments],
    }
    return {"query": term, "total": sum(len(v) for v in results.values()), "results": results}


# ---------------------------------------------------------------------------
# Observability: request id, access log, liveness/readiness, metrics
# ---------------------------------------------------------------------------

class _Metrics:
    def __init__(self) -> None:
        self.requests: Counter[tuple[str, str]] = Counter()
        self.latency_sum = 0.0
        self.latency_count = 0
        self.slow_requests = 0

    def observe(self, method: str, status: int, seconds: float) -> None:
        self.requests[(method, f"{status // 100}xx")] += 1
        self.latency_sum += seconds; self.latency_count += 1
        if seconds > 1.5:
            self.slow_requests += 1


METRICS = _Metrics()


def install_observability(app: FastAPI) -> None:
    """Attach request-id propagation, JSON access logging and latency counters."""

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id", "")
        rid = rid if re.fullmatch(r"[A-Za-z0-9._\-]{8,64}", rid or "") else uuid.uuid4().hex
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            elapsed = time.perf_counter() - started
            METRICS.observe(request.method, status_code, elapsed)
            if request.url.path.startswith("/api/") and request.url.path not in {"/api/health", "/api/health/live"}:
                logger.info(json.dumps({"event": "request", "request_id": rid, "method": request.method,
                                        "path": request.url.path, "status": status_code,
                                        "ms": round(elapsed * 1000, 1)}))


@router.get("/health/live")
def live() -> dict[str, Any]:
    return {"status": "alive", "version": APP_VERSION, "uptime_seconds": int(time.time() - _STARTED_AT)}


@router.get("/health/ready")
def ready() -> dict[str, Any]:
    checks: dict[str, Any] = {}
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
            try:
                checks["migrations_applied"] = conn.execute(text("SELECT COUNT(*) FROM schema_migrations")).scalar()
            except Exception:
                checks["migrations_applied"] = 0
    except Exception as exc:
        logger.warning("readiness: database unavailable (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Database is unavailable.") from exc
    from .config import STORAGE_DIR
    try:
        probe = STORAGE_DIR / f".ready-{secrets.token_hex(4)}"
        probe.write_text("ok"); probe.unlink()
        checks["storage"] = "writable"
    except OSError:
        raise HTTPException(status_code=503, detail="Upload storage is not writable.")
    return {"status": "ready", "version": APP_VERSION, "checks": checks}


@router.get("/metrics", include_in_schema=False)
def metrics(request: Request):
    """Prometheus text format. Process-level only (no tenant data). Disabled unless METRICS_TOKEN is set."""
    supplied = request.headers.get("x-metrics-token", "")
    if not METRICS_TOKEN or not secrets.compare_digest(supplied, METRICS_TOKEN):
        raise HTTPException(status_code=404, detail="Not found.")
    lines = ["# TYPE contexa_http_requests_total counter"]
    for (method, klass), n in sorted(METRICS.requests.items()):
        lines.append(f'contexa_http_requests_total{{method="{method}",status="{klass}"}} {n}')
    lines += ["# TYPE contexa_http_request_seconds_sum counter", f"contexa_http_request_seconds_sum {METRICS.latency_sum:.4f}",
              "# TYPE contexa_http_request_seconds_count counter", f"contexa_http_request_seconds_count {METRICS.latency_count}",
              "# TYPE contexa_http_slow_requests_total counter", f"contexa_http_slow_requests_total {METRICS.slow_requests}",
              "# TYPE contexa_uptime_seconds gauge", f"contexa_uptime_seconds {int(time.time() - _STARTED_AT)}"]
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
