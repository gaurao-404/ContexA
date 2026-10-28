from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import fitz
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc, func, inspect as sqlalchemy_inspect, select, text
from sqlalchemy.orm import Session, joinedload

from .config import APP_ENV, APP_NAME, MAX_UPLOAD_MB, STORAGE_DIR, WORKSPACE_ID, ANTHROPIC_API_KEY, ANTHROPIC_MODEL, DATABASE_URL, OLLAMA_MODEL, AI_VERIFICATION_ENABLED
from .database import Base, SessionLocal, engine, get_db, prepare_database
from .embeddings import embed, hybrid_score
from .inspection import inspect_content, local_ai_status
from .models import AuditEvent, BrandRule, ContentDocument, ReviewFinding, User, utcnow
from .parsing import ALLOWED_EXTENSIONS, parse_document
from .schemas import (DashboardOut, DocumentOut, FindingAction, FindingActionResponse, FindingOut,
                      InsightOut, InsightRule, LoginRequest, LoginResponse, PublishRequest,
                      RuleCreate, RuleOut, RuleUpdate, UserOut, CopyCheckRequest)
from .security import create_access_token, get_current_user, hash_password, require_roles, verify_password

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("contexa")

app = FastAPI(title=APP_NAME, version="1.0.0", description="Pre-publication brand-governance and audit platform")
_default_origins = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173"
_allowed_origins = [origin.strip().rstrip("/") for origin in os.getenv("ALLOWED_ORIGINS", _default_origins).split(",") if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_allowed_origins,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

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


def _audit(db: Session, user: User, action: str, entity_type: str, entity_id: str,
           detail: dict[str, Any] | None = None) -> AuditEvent:
    event = AuditEvent(workspace_id=WORKSPACE_ID, actor_id=user.id, actor_name=user.name,
        action=action, entity_type=entity_type, entity_id=entity_id, detail=detail or {})
    db.add(event)
    return event


def _seed() -> None:
    Base.metadata.create_all(bind=engine)
    # Tiny forward-compatible SQLite migration for fields added during the MVP build.
    if DATABASE_URL.startswith("sqlite"):
        try:
            columns = {c["name"] for c in sqlalchemy_inspect(engine).get_columns("review_findings")}
            if "applied_text" not in columns:
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE review_findings ADD COLUMN applied_text TEXT"))
        except Exception:
            logger.exception("SQLite schema migration could not be applied")
    if DATABASE_URL.startswith("postgresql"):
        try:
            with engine.begin() as conn:
                conn.execute(text("CREATE INDEX IF NOT EXISTS brand_rules_embedding_hnsw ON brand_rules USING hnsw (embedding vector_cosine_ops)"))
        except Exception:
            logger.exception("Could not create pgvector HNSW index; rule search will still have a hybrid application-level fallback")
    with SessionLocal() as db:
        users = [
            ("ContexA Admin", "admin@contexa.local", "Brand Admin", "ContexA!2026"),
            ("Alex Morgan", "manager@contexa.local", "Manager", "Manager!2026"),
            ("Jordan Lee", "creator@contexa.local", "Creator", "Creator!2026"),
            ("Sam Rivera", "legal@contexa.local", "SME / Legal", "Legal!2026"),
        ]
        for name, email, role, password in users:
            if not db.scalar(select(User).where(User.email == email)):
                db.add(User(name=name, email=email, role=role, password_hash=hash_password(password)))
        db.flush()
        for item in SEED_RULES:
            existing = db.scalar(select(BrandRule).where(BrandRule.workspace_id == WORKSPACE_ID, BrandRule.code == item["code"]))
            if not existing:
                db.add(BrandRule(workspace_id=WORKSPACE_ID, **item,
                    embedding=embed(f"{item['title']} {item['category']} {item['rule_clause']}")))
        db.commit()


@app.on_event("startup")
def startup() -> None:
    prepare_database()
    _seed()



def _retrieve_ai_candidates(db: Session, content: str, rules: list[BrandRule]) -> list[BrandRule]:
    """Retrieve a small RAG context using pgvector cosine distance plus lexical reranking.

    SQLite local mode uses deterministic hashed embeddings and the same hybrid ranking in Python.
    PostgreSQL mode first asks pgvector for nearest neighbors, then reranks them with lexical overlap.
    """
    active = [r for r in rules if r.is_active]
    if not active:
        return []
    query_text = content[:12000]
    selected: list[BrandRule] = []
    if DATABASE_URL.startswith("postgresql"):
        try:
            vector_literal = "[" + ",".join(f"{v:.8f}" for v in embed(query_text)) + "]"
            result = db.execute(text("""SELECT id FROM brand_rules
                WHERE workspace_id = :workspace_id AND is_active = TRUE AND embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:query_vector AS vector) LIMIT 12"""),
                {"workspace_id": WORKSPACE_ID, "query_vector": vector_literal}).all()
            by_id = {r.id: r for r in active}
            selected = [by_id[str(row[0])] for row in result if str(row[0]) in by_id]
        except Exception:
            logger.exception("pgvector retrieval failed; using local hybrid reranking")
    # A lexical pass gives exact terminology/claim rules a path into the candidate set even
    # when the vector model is only the lightweight local hashed embedder.
    lexical = sorted(active, key=lambda r: hybrid_score(query_text, f"{r.title} {r.category} {r.rule_clause}", r.embedding), reverse=True)[:8]
    union: dict[str, BrandRule] = {r.id: r for r in [*selected, *lexical]}
    return sorted(union.values(), key=lambda r: hybrid_score(query_text, f"{r.title} {r.category} {r.rule_clause}", r.embedding), reverse=True)[:5]

def _finding_out(finding: ReviewFinding) -> dict[str, Any]:
    return {
        "id": finding.id, "content_id": finding.content_id, "rule_id": finding.rule_id,
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
        "size_bytes": doc.size_bytes, "created_by": doc.created_by,
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


def _get_doc(doc_id: str, db: Session) -> ContentDocument:
    doc = db.get(ContentDocument, doc_id)
    if not doc or doc.workspace_id != WORKSPACE_ID:
        raise HTTPException(status_code=404, detail="Document not found.")
    return doc


@app.get("/api/health")
def health() -> dict[str, Any]:
    local_status = local_ai_status()
    return {"status": "ok", "app": APP_NAME, "environment": APP_ENV,
            "ai_configured": bool(local_status.get("model_available") or ANTHROPIC_API_KEY),
            "ai_model": OLLAMA_MODEL if local_status.get("model_available") else (ANTHROPIC_MODEL if ANTHROPIC_API_KEY else None),
            "local_ai": local_status,
            "database": "postgresql" if DATABASE_URL.startswith("postgresql") else "sqlite"}


@app.post("/api/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    return {"access_token": create_access_token(user), "token_type": "bearer", "user": user}


@app.get("/api/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@app.get("/api/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), user: User = Depends(require_roles("Brand Admin"))):
    return db.scalars(select(User).order_by(User.name)).all()


@app.post("/api/users", response_model=UserOut, status_code=201)
def create_user(payload: dict[str, Any], db: Session = Depends(get_db), user: User = Depends(require_roles("Brand Admin"))):
    name, email, password, role = (str(payload.get(k, "")).strip() for k in ("name", "email", "password", "role"))
    if not name or not email or len(password) < 10 or role not in ROLES:
        raise HTTPException(status_code=422, detail="Name, valid email, a 10+ character password and a supported role are required.")
    if db.scalar(select(User).where(User.email == email.lower())):
        raise HTTPException(status_code=409, detail="A user with this email already exists.")
    new_user = User(name=name, email=email.lower(), password_hash=hash_password(password), role=role)
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
        BrandRule.workspace_id == WORKSPACE_ID, BrandRule.is_active.is_(True)
    )).all()
    existing_names = set(db.scalars(select(ContentDocument.filename).where(
        ContentDocument.workspace_id == WORKSPACE_ID,
        ContentDocument.filename.in_([name for name, _ in samples])
    )).all())
    created = 0
    for filename, content in samples:
        if filename in existing_names:
            continue
        data = content.encode("utf-8")
        stored_path = STORAGE_DIR / f"demo-{uuid.uuid4()}.txt"
        stored_path.write_bytes(data)
        pages = [{"page": 1, "text": content, "spans": []}]
        doc = ContentDocument(
            id=str(uuid.uuid4()), workspace_id=WORKSPACE_ID, filename=filename,
            stored_path=str(stored_path), content_type="text/plain", content_text=content,
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
    _audit(db, user, "demo.workspace_prepared", "workspace", WORKSPACE_ID,
           {"created_documents": created, "ai_used": False})
    db.commit()
    documents = db.scalars(select(ContentDocument).where(
        ContentDocument.workspace_id == WORKSPACE_ID,
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
    docs = db.scalars(select(ContentDocument).where(ContentDocument.workspace_id == WORKSPACE_ID).order_by(desc(ContentDocument.updated_at))).all()
    all_findings = db.scalars(select(ReviewFinding).join(ContentDocument).where(ContentDocument.workspace_id == WORKSPACE_ID)).all()
    open_findings = [f for f in all_findings if f.status == "open"]
    active_rules = db.scalar(select(func.count()).select_from(BrandRule).where(BrandRule.workspace_id == WORKSPACE_ID, BrandRule.is_active.is_(True))) or 0
    score = int(round(sum(d.compliance_score for d in docs) / len(docs))) if docs else 100
    activities = db.scalars(select(AuditEvent).where(AuditEvent.workspace_id == WORKSPACE_ID).order_by(desc(AuditEvent.created_at)).limit(8)).all()
    daily = Counter()
    today = datetime.now(timezone.utc).date()
    for event in db.scalars(select(AuditEvent).where(AuditEvent.workspace_id == WORKSPACE_ID, AuditEvent.created_at >= datetime.now(timezone.utc) - timedelta(days=6))).all():
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
        BrandRule.workspace_id == WORKSPACE_ID, BrandRule.is_active.is_(True)
    )).all()
    findings = inspect_content(content, [{"page": 1, "text": content, "spans": []}], rules, ai_candidates=rules)
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
    query = select(ContentDocument).where(ContentDocument.workspace_id == WORKSPACE_ID).order_by(desc(ContentDocument.updated_at))
    if q:
        query = query.where(ContentDocument.filename.ilike(f"%{q[:100]}%"))
    if status_filter and status_filter != "all":
        query = query.where(ContentDocument.status == status_filter)
    return [_document_out(doc, db) for doc in db.scalars(query).all()]


@app.post("/api/documents/upload", response_model=DocumentOut, status_code=201)
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    filename = Path(file.filename or "upload").name[:255]
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Supported formats: PDF, DOCX, PPTX, TXT, MD, PNG, JPG, TIFF and BMP.")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds the {MAX_UPLOAD_MB} MB upload limit.")
    try:
        pages, content = parse_document(filename, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Document parse failed")
        raise HTTPException(status_code=422, detail="Unable to parse this file. Confirm that it is a valid, unencrypted document.") from exc
    has_supported_visual_findings = any(page.get("missing_alt_text") for page in pages)
    if not content.strip() and not has_supported_visual_findings:
        raise HTTPException(status_code=422, detail="No readable text was found. For scanned PDFs, run OCR first or upload an OCR-readable version.")
    doc_id = str(uuid.uuid4())
    safe_disk_name = f"{doc_id}{suffix}"
    stored_path = STORAGE_DIR / safe_disk_name
    stored_path.write_bytes(data)
    doc = ContentDocument(id=doc_id, workspace_id=WORKSPACE_ID, filename=filename, stored_path=str(stored_path),
        content_type=file.content_type or "application/octet-stream", content_text=content,
        pages_json=pages, page_count=len(pages), status="IN_REVIEW", compliance_score=100,
        size_bytes=len(data), created_by=user.id)
    db.add(doc); db.flush()
    rules = db.scalars(select(BrandRule).where(BrandRule.workspace_id == WORKSPACE_ID, BrandRule.is_active.is_(True))).all()
    proposed = inspect_content(content, pages, rules, _retrieve_ai_candidates(db, content, rules))
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
    for item in proposed:
        db.add(ReviewFinding(content_id=doc.id, **item))
    db.flush(); _recompute_document(doc, db)
    _audit(db, user, "document.uploaded_and_scanned", "document", doc.id,
           {"filename": filename, "page_count": len(pages), "finding_count": len(proposed), "bytes": len(data)})
    db.commit(); db.refresh(doc)
    return _document_out(doc, db)


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = _get_doc(doc_id, db)
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
    doc = _get_doc(doc_id, db)
    if page_number < 1 or page_number > doc.page_count:
        raise HTTPException(status_code=404, detail="Page not found.")
    suffix = Path(doc.filename).suffix.lower()
    if suffix == ".pdf":
        try:
            pdf = fitz.open(doc.stored_path)
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
    doc = _get_doc(doc_id, db)
    if doc.status == "PUBLISH_READY":
        raise HTTPException(status_code=409, detail="Published documents cannot be rescanned in place. Upload a new version.")
    db.query(ReviewFinding).filter(ReviewFinding.content_id == doc.id).delete(synchronize_session=False)
    rules = db.scalars(select(BrandRule).where(BrandRule.workspace_id == WORKSPACE_ID, BrandRule.is_active.is_(True))).all()
    for item in inspect_content(doc.content_text, doc.pages_json, rules, _retrieve_ai_candidates(db, doc.content_text, rules)):
        db.add(ReviewFinding(content_id=doc.id, **item))
    db.flush(); _recompute_document(doc, db)
    _audit(db, user, "document.rescanned", "document", doc.id, {"rule_count": len(rules)})
    db.commit(); db.refresh(doc)
    return _document_out(doc, db)


@app.delete("/api/documents/{doc_id}", status_code=204)
def delete_document(doc_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("Manager", "Brand Admin"))):
    doc = _get_doc(doc_id, db)
    path = Path(doc.stored_path)
    _audit(db, user, "document.deleted", "document", doc.id, {"filename": doc.filename})
    db.delete(doc); db.commit()
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove stored upload %s", path)
    return Response(status_code=204)


@app.post("/api/findings/{finding_id}/action", response_model=FindingActionResponse)
def finding_action(finding_id: str, payload: FindingAction, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    finding = db.scalar(select(ReviewFinding).options(joinedload(ReviewFinding.rule)).where(ReviewFinding.id == finding_id))
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found.")
    doc = _get_doc(finding.content_id, db)
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
    db.commit(); db.refresh(finding)
    finding = db.scalar(select(ReviewFinding).options(joinedload(ReviewFinding.rule)).where(ReviewFinding.id == finding_id))
    open_critical = db.scalar(select(func.count()).select_from(ReviewFinding).where(
        ReviewFinding.content_id == doc.id, ReviewFinding.status == "open", ReviewFinding.severity == "critical")) or 0
    return {"finding": _finding_out(finding), "publish_ready": open_critical == 0}


@app.post("/api/documents/{doc_id}/publish")
def publish_document(doc_id: str, payload: PublishRequest, db: Session = Depends(get_db), user: User = Depends(require_roles("Manager", "SME / Legal", "Brand Admin"))):
    doc = _get_doc(doc_id, db)
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
    db.commit(); db.refresh(doc)
    return {"document": _document_out(doc, db), "message": "Document marked Publish Ready. This records governance approval; it does not publish the file to an external channel."}


@app.get("/api/documents/{doc_id}/export")
def export_document(doc_id: str, fmt: str = Query(default="json", pattern="^(json|csv)$"), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = _get_doc(doc_id, db)
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


@app.post("/api/guidelines/import")
async def import_guideline(file: UploadFile = File(...), db: Session = Depends(get_db),
                           user: User = Depends(require_roles("Brand Admin"))):
    """Import policy content into paused rule candidates for a Brand Admin to review."""
    filename = Path(file.filename or "guideline").name[:255]
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Supported guideline sources: PDF, DOCX, PPTX, TXT, Markdown or image OCR formats.")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="The guideline file is empty.")
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds the {MAX_UPLOAD_MB} MB upload limit.")
    try:
        pages, content = parse_document(filename, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Guideline import parse failed")
        raise HTTPException(status_code=422, detail="Unable to parse the guideline file. Confirm it is a valid, unencrypted document.") from exc
    if not content.strip():
        raise HTTPException(status_code=422, detail="No readable guideline text was extracted. Run OCR on scanned pages, then try again.")
    clauses = _extract_guideline_clauses(content)
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
        rule = BrandRule(workspace_id=WORKSPACE_ID, code=code, title=title,
            category=category, rule_clause=clause, source_document=filename, pattern=pattern,
            severity=severity,
            suggested_fix="Review this extracted clause, confirm its meaning and add a deterministic pattern or enable grounded contextual review where appropriate.",
            embedding=embed(f"{title} {category} {clause}"), is_active=False)
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


@app.get("/api/rules", response_model=list[RuleOut])
def list_rules(q: str | None = None, active_only: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = select(BrandRule).where(BrandRule.workspace_id == WORKSPACE_ID).order_by(BrandRule.code)
    if q:
        query = query.where((BrandRule.code.ilike(f"%{q[:80]}%")) | (BrandRule.title.ilike(f"%{q[:120]}%")) | (BrandRule.rule_clause.ilike(f"%{q[:120]}%")) | (BrandRule.source_document.ilike(f"%{q[:120]}%")))
    if active_only:
        query = query.where(BrandRule.is_active.is_(True))
    return db.scalars(query).all()


@app.post("/api/rules", response_model=RuleOut, status_code=201)
def create_rule(payload: RuleCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("Brand Admin"))):
    if db.scalar(select(BrandRule).where(BrandRule.workspace_id == WORKSPACE_ID, BrandRule.code == payload.code.upper())):
        raise HTTPException(status_code=409, detail="That rule code already exists in this workspace.")
    if payload.pattern:
        try: re.compile(payload.pattern)
        except re.error as exc: raise HTTPException(status_code=422, detail=f"Invalid regex pattern: {exc}") from exc
    data = payload.model_dump(); data["code"] = data["code"].upper()
    rule = BrandRule(workspace_id=WORKSPACE_ID, **data, embedding=embed(f"{payload.title} {payload.category} {payload.rule_clause}"))
    db.add(rule); db.flush()
    _audit(db, user, "rule.created", "rule", rule.id, {"code": rule.code})
    db.commit(); db.refresh(rule)
    return rule


@app.patch("/api/rules/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: str, payload: RuleUpdate, db: Session = Depends(get_db), user: User = Depends(require_roles("Brand Admin"))):
    rule = db.get(BrandRule, rule_id)
    if not rule or rule.workspace_id != WORKSPACE_ID:
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
    _audit(db, user, "rule.updated", "rule", rule.id, {"fields": sorted(data.keys()), "code": rule.code})
    db.commit(); db.refresh(rule)
    return rule


@app.get("/api/insights", response_model=InsightOut)
def insights(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rules = db.scalars(select(BrandRule).where(BrandRule.workspace_id == WORKSPACE_ID).order_by(BrandRule.code)).all()
    findings = db.scalars(select(ReviewFinding).join(ContentDocument).where(ContentDocument.workspace_id == WORKSPACE_ID)).all()
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


@app.get("/api/audit")
def audit_log(limit: int = Query(default=100, ge=1, le=500), entity_type: str | None = None,
              db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = select(AuditEvent).where(AuditEvent.workspace_id == WORKSPACE_ID).order_by(desc(AuditEvent.created_at))
    if entity_type:
        query = query.where(AuditEvent.entity_type == entity_type)
    events = db.scalars(query.limit(limit)).all()
    return [{"id": a.id, "actor_id": a.actor_id, "actor_name": a.actor_name, "action": a.action,
             "entity_type": a.entity_type, "entity_id": a.entity_id, "detail": a.detail, "created_at": a.created_at} for a in events]


@app.get("/api/settings")
def settings(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    local_status = local_ai_status()
    local_ready = bool(local_status.get("model_available"))
    return {"workspace": {"id": WORKSPACE_ID, "name": "ContexA Studio", "environment": APP_ENV},
            "backend": {"database": "postgresql + pgvector" if DATABASE_URL.startswith("postgresql") else "SQLite (local development)",
                        "upload_limit_mb": MAX_UPLOAD_MB, "ai_configured": local_ready or bool(ANTHROPIC_API_KEY),
                        "ai_model": OLLAMA_MODEL if local_ready else (ANTHROPIC_MODEL if ANTHROPIC_API_KEY else None),
                        "ai_provider": "Ollama local" if local_ready else ("Claude API" if ANTHROPIC_API_KEY else "Deterministic rules only"),
                        "local_ai": local_status,
                        "ai_note": "No API key is required. Install Ollama and pull the configured model for local contextual verification. Deterministic checks always work without local AI."},
            "roles": ROLES, "current_user": {"name": user.name, "email": user.email, "role": user.role},
            "permissions": {"rule_management": user.role == "Brand Admin",
                "manage_users": user.role == "Brand Admin", "publish_signoff": user.role in {"Manager", "SME / Legal", "Brand Admin"},
                "delete_documents": user.role in {"Manager", "Brand Admin"}, "run_rescan": user.role in {"Manager", "SME / Legal", "Brand Admin"}}}


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
