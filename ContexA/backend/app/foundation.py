"""Enterprise identity, provenance graph, replay and evidence anchoring APIs."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select, func, text
from sqlalchemy.orm import Session

from .cloud_providers import archive_evidence, canonical_json, provider_readiness, sign_manifest, verify_manifest
from .config import APP_ENV, AUTH_MODE, SUPABASE_AUTH_ENABLED, SUPABASE_URL, SUPABASE_JWT_ISSUER, SUPABASE_JWKS_URL, SUPABASE_REQUIRE_AAL2
from .database import engine, get_db
from .models import (
    AgentRun, ApprovedFact, AuditEvent, BrandIncident, ContentDocument, DecisionTrace,
    EvidenceArchive, EvidenceGraphEdge, EvidenceGraphNode, EvidenceMerkleAnchor,
    MonitoredSource, PublicPassportIndex, PassportSignature, TrustPassport, User, utcnow,
)
from .security import get_current_user, require_roles

router = APIRouter(prefix="/api/foundation", tags=["ContexA Enterprise Trust Foundation"])


class GraphNodeIn(BaseModel):
    node_type: str = Field(min_length=2, max_length=40)
    external_id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=240)
    attributes: dict[str, Any] = Field(default_factory=dict)


class GraphEdgeIn(BaseModel):
    source_node_id: str
    target_node_id: str
    relation: str = Field(min_length=2, max_length=60)
    attributes: dict[str, Any] = Field(default_factory=dict)


def _audit(db: Session, user: User, action: str, entity_type: str, entity_id: str, detail: dict | None = None):
    # Serialize audit-head updates on PostgreSQL and preserve continuity when an
    # older deployment contains a legacy event without its event_hash populated.
    if engine.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:workspace_id))"), {"workspace_id": user.workspace_id})
    previous = db.scalar(select(AuditEvent).where(AuditEvent.workspace_id == user.workspace_id)
                         .order_by(desc(AuditEvent.created_at), desc(AuditEvent.id)).limit(1))
    if previous and previous.event_hash:
        prev_hash = previous.event_hash
    elif previous:
        previous_created = previous.created_at
        if previous_created is not None and previous_created.tzinfo is None:
            previous_created = previous_created.replace(tzinfo=timezone.utc)
        legacy = {"id": previous.id, "workspace_id": previous.workspace_id,
            "actor_id": previous.actor_id, "actor_name": previous.actor_name,
            "action": previous.action, "entity_type": previous.entity_type,
            "entity_id": previous.entity_id, "detail": previous.detail or {},
            "created_at": previous_created.isoformat() if previous_created else None,
            "previous_hash": previous.previous_hash or "0" * 64}
        prev_hash = hashlib.sha256(canonical_json(legacy)).hexdigest()
    else:
        prev_hash = "0" * 64
    event = AuditEvent(id=str(uuid.uuid4()), workspace_id=user.workspace_id, actor_id=user.id,
        actor_name=user.name, action=action, entity_type=entity_type, entity_id=entity_id,
        detail=detail or {}, previous_hash=prev_hash, created_at=utcnow())
    canonical = {"id": event.id, "workspace_id": event.workspace_id, "actor_id": event.actor_id,
        "actor_name": event.actor_name, "action": event.action, "entity_type": event.entity_type,
        "entity_id": event.entity_id, "detail": event.detail,
        "created_at": event.created_at.isoformat(), "previous_hash": prev_hash}
    event.event_hash = hashlib.sha256(canonical_json(canonical)).hexdigest()
    db.add(event)


def _node(db: Session, workspace_id: str, node_type: str, external_id: str,
          label: str, attributes: dict[str, Any] | None = None) -> EvidenceGraphNode:
    row = db.scalar(select(EvidenceGraphNode).where(
        EvidenceGraphNode.workspace_id == workspace_id,
        EvidenceGraphNode.node_type == node_type,
        EvidenceGraphNode.external_id == external_id,
    ))
    if row:
        row.label = label
        row.attributes = attributes or {}
        return row
    row = EvidenceGraphNode(workspace_id=workspace_id, node_type=node_type,
        external_id=external_id, label=label, attributes=attributes or {})
    db.add(row); db.flush()
    return row


def _edge(db: Session, workspace_id: str, source: EvidenceGraphNode,
          target: EvidenceGraphNode, relation: str, attributes: dict | None = None):
    if source.id == target.id:
        return
    exists = db.scalar(select(EvidenceGraphEdge).where(
        EvidenceGraphEdge.workspace_id == workspace_id,
        EvidenceGraphEdge.source_node_id == source.id,
        EvidenceGraphEdge.target_node_id == target.id,
        EvidenceGraphEdge.relation == relation,
    ))
    if exists:
        return
    db.add(EvidenceGraphEdge(workspace_id=workspace_id, source_node_id=source.id,
        target_node_id=target.id, relation=relation, attributes=attributes or {}))


@router.get("/status")
def foundation_status(user: User = Depends(get_current_user)):
    readiness = provider_readiness()
    return {
        "identity": {"provider": "supabase" if SUPABASE_AUTH_ENABLED else "contexa_local",
                     "configured": bool(SUPABASE_AUTH_ENABLED and SUPABASE_URL and SUPABASE_JWT_ISSUER and SUPABASE_JWKS_URL),
                     "mode": AUTH_MODE,
                     "mfa_enforcement": "aal2_enforced" if SUPABASE_AUTH_ENABLED and SUPABASE_REQUIRE_AAL2 else ("provider_policy_not_backend_enforced" if SUPABASE_AUTH_ENABLED else "local_auth_only"),
                     "note": "Supabase JWT signatures, issuer, audience and verified-email claims are checked server-side. Workspace and role permissions always come from the ContexA account record."},
        **readiness,
        "trust_graph": {"enabled": True, "model": "workspace-scoped nodes and typed edges"},
        "decision_replay": {"enabled": True, "replay_type": "integrity_replay_not_model_reexecution"},
        "audit_anchors": {"enabled": True, "model": "Merkle root signed by configured trust signer"},
        "current_workspace": user.workspace_id,
    }


@router.post("/graph/rebuild")
def rebuild_trust_graph(db: Session = Depends(get_db), user: User = Depends(require_roles("Manager", "SME / Legal", "Brand Admin"))):
    ws = user.workspace_id
    stats = {"documents": 0, "facts": 0, "sources": 0, "passports": 0, "drifts": 0,
             "incidents": 0, "agent_runs": 0, "edges": 0}
    maps: dict[tuple[str, str], EvidenceGraphNode] = {}
    docs = db.scalars(select(ContentDocument).where(ContentDocument.workspace_id == ws)).all()
    for item in docs:
        maps[("document", item.id)] = _node(db, ws, "document", item.id, item.filename,
            {"sha256": item.sha256, "status": item.status, "content_type": item.content_type})
        stats["documents"] += 1
    facts = db.scalars(select(ApprovedFact).where(ApprovedFact.workspace_id == ws)).all()
    for item in facts:
        maps[("claim", item.id)] = _node(db, ws, "claim", item.id, item.fact_key,
            {"status": item.status, "source_document": item.source_document, "version": item.version_number})
        stats["facts"] += 1
    sources = db.scalars(select(MonitoredSource).where(MonitoredSource.workspace_id == ws)).all()
    for item in sources:
        maps[("source", item.id)] = _node(db, ws, "source", item.id, item.name,
            {"url": item.source_url, "authority": item.authority, "last_status": item.last_status,
             "last_sha256": item.last_sha256})
        stats["sources"] += 1
    passports = db.scalars(select(TrustPassport).where(TrustPassport.workspace_id == ws)).all()
    for item in passports:
        maps[("passport", item.id)] = _node(db, ws, "passport", item.id, item.title,
            {"public_id": item.public_id, "status": item.status, "asset_sha256": item.asset_sha256})
        doc_node = maps.get(("document", item.document_id))
        if doc_node:
            _edge(db, ws, maps[("passport", item.id)], doc_node, "attests_asset")
            stats["edges"] += 1
        stats["passports"] += 1
    from .models import TruthDriftEvent
    drifts = db.scalars(select(TruthDriftEvent).where(TruthDriftEvent.workspace_id == ws)).all()
    for item in drifts:
        node = _node(db, ws, "drift_event", item.id, item.title,
            {"event_type": item.event_type, "severity": item.severity, "status": item.status})
        source_node = maps.get(("source", item.source_id)) if item.source_id else None
        fact_node = maps.get(("claim", item.fact_id)) if item.fact_id else None
        if source_node: _edge(db, ws, source_node, node, "changed_into"); stats["edges"] += 1
        if fact_node: _edge(db, ws, fact_node, node, "potentially_impacted_by"); stats["edges"] += 1
        stats["drifts"] += 1
    incidents = db.scalars(select(BrandIncident).where(BrandIncident.workspace_id == ws)).all()
    for item in incidents:
        node = _node(db, ws, "incident", item.id, item.title,
            {"severity": item.severity, "status": item.status, "source_type": item.source_type})
        source_node = maps.get(("source", item.source_id)) if item.source_id else None
        if source_node: _edge(db, ws, source_node, node, "raised_incident"); stats["edges"] += 1
        for doc_id in item.affected_document_ids or []:
            doc_node = maps.get(("document", doc_id))
            if doc_node: _edge(db, ws, node, doc_node, "affects_asset"); stats["edges"] += 1
        stats["incidents"] += 1
    runs = db.scalars(select(AgentRun).where(AgentRun.workspace_id == ws)).all()
    for item in runs:
        node = _node(db, ws, "agent_run", item.id, item.objective,
            {"status": item.status, "requires_human_review": item.requires_human_review})
        doc_node = maps.get(("document", item.document_id)) if item.document_id else None
        if doc_node: _edge(db, ws, node, doc_node, "reviewed_asset"); stats["edges"] += 1
        stats["agent_runs"] += 1
    _audit(db, user, "trust_graph.rebuilt", "trust_graph", ws, stats)
    db.commit()
    return {"workspace_id": ws, "counts": stats, "note": "Graph nodes are derived from existing workspace records; relationships reflect stored IDs and workflows, not inferred factual truth."}


@router.get("/graph")
def get_trust_graph(limit: int = Query(default=300, ge=1, le=1000), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    nodes = db.scalars(select(EvidenceGraphNode).where(EvidenceGraphNode.workspace_id == user.workspace_id)
        .order_by(desc(EvidenceGraphNode.created_at)).limit(limit)).all()
    node_ids = [x.id for x in nodes]
    edges = db.scalars(select(EvidenceGraphEdge).where(EvidenceGraphEdge.workspace_id == user.workspace_id,
        EvidenceGraphEdge.source_node_id.in_(node_ids) if node_ids else False,
        EvidenceGraphEdge.target_node_id.in_(node_ids) if node_ids else False).limit(3000)).all()
    return {"nodes": [{"id": x.id, "node_type": x.node_type, "external_id": x.external_id,
        "label": x.label, "attributes": x.attributes, "created_at": x.created_at.isoformat()} for x in nodes],
        "edges": [{"id": x.id, "source": x.source_node_id, "target": x.target_node_id,
                   "relation": x.relation, "attributes": x.attributes} for x in edges]}


@router.post("/graph/nodes", status_code=201)
def create_graph_node(payload: GraphNodeIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = _node(db, user.workspace_id, payload.node_type, payload.external_id, payload.label, payload.attributes)
    db.commit(); db.refresh(row)
    return {"id": row.id, "node_type": row.node_type, "external_id": row.external_id, "label": row.label}


@router.post("/graph/edges", status_code=201)
def create_graph_edge(payload: GraphEdgeIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    src = db.scalar(select(EvidenceGraphNode).where(EvidenceGraphNode.id == payload.source_node_id,
        EvidenceGraphNode.workspace_id == user.workspace_id))
    dst = db.scalar(select(EvidenceGraphNode).where(EvidenceGraphNode.id == payload.target_node_id,
        EvidenceGraphNode.workspace_id == user.workspace_id))
    if not src or not dst:
        raise HTTPException(404, "Both graph endpoints must exist in the active workspace.")
    _edge(db, user.workspace_id, src, dst, payload.relation, payload.attributes)
    db.commit()
    return {"created": True, "source": src.id, "target": dst.id, "relation": payload.relation}


@router.get("/decision-traces")
def list_decision_traces(limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(DecisionTrace).where(DecisionTrace.workspace_id == user.workspace_id)
        .order_by(desc(DecisionTrace.created_at)).limit(limit)).all()
    return [{"id": x.id, "operation": x.operation, "model_id": x.model_id,
        "prompt_version": x.prompt_version, "input_sha256": x.input_sha256,
        "output_sha256": x.output_sha256, "evidence_refs": x.evidence_refs,
        "agent_run_id": x.agent_run_id, "integrity_sha256": x.integrity_sha256,
        "created_at": x.created_at.isoformat()} for x in rows]


@router.get("/decision-traces/{trace_id}/replay")
def replay_decision_trace(trace_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.scalar(select(DecisionTrace).where(DecisionTrace.id == trace_id, DecisionTrace.workspace_id == user.workspace_id))
    if not row:
        raise HTTPException(404, "Decision trace not found.")
    trace_bytes = canonical_json(row.trace)
    computed_integrity = hashlib.sha256(trace_bytes).hexdigest()
    actual_output = hashlib.sha256(canonical_json(row.trace.get("output", {}))).hexdigest()
    actual_input = hashlib.sha256(canonical_json(row.trace.get("input", {}))).hexdigest()
    return {"id": row.id, "integrity_valid": computed_integrity == row.integrity_sha256,
        "input_hash_valid": actual_input == row.input_sha256,
        "output_hash_valid": actual_output == row.output_sha256,
        "operation": row.operation, "model_id": row.model_id, "prompt_version": row.prompt_version,
        "trace": row.trace, "note": "Replay validates the stored execution record and hashes. It does not re-execute an external model or prove that the model's conclusion was correct."}


@router.get("/evidence-archives")
def list_evidence_archives(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(EvidenceArchive).where(EvidenceArchive.workspace_id == user.workspace_id)
        .order_by(desc(EvidenceArchive.created_at)).limit(100)).all()
    return [{"id": x.id, "subject_type": x.subject_type, "subject_id": x.subject_id,
        "sha256": x.sha256, "storage_provider": x.storage_provider,
        "storage_uri": x.storage_uri, "object_lock_mode": x.object_lock_mode,
        "retain_until": x.retain_until.isoformat() if x.retain_until else None,
        "status": x.status, "created_at": x.created_at.isoformat()} for x in rows]


@router.get("/audit/anchors")
def list_audit_anchors(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(select(EvidenceMerkleAnchor).where(EvidenceMerkleAnchor.workspace_id == user.workspace_id)
        .order_by(desc(EvidenceMerkleAnchor.created_at)).limit(50)).all()
    return [{"id": x.id, "leaf_count": x.leaf_count, "root_sha256": x.root_sha256,
        "previous_anchor_sha256": x.previous_anchor_sha256, "signing_provider": x.signing_provider,
        "signing_key_id": x.signing_key_id, "signature_algorithm": x.signature_algorithm,
        "signature_b64": x.signature_b64, "created_at": x.created_at.isoformat()} for x in rows]


@router.post("/audit/anchors", status_code=201)
def anchor_audit_chain(db: Session = Depends(get_db), user: User = Depends(require_roles("Brand Admin"))):
    events = db.scalars(select(AuditEvent).where(AuditEvent.workspace_id == user.workspace_id)
        .order_by(AuditEvent.created_at, AuditEvent.id)).all()
    leaves = [bytes.fromhex(x.event_hash) for x in events if x.event_hash and len(x.event_hash) == 64]
    if not leaves:
        raise HTTPException(409, "No hash-chained audit events are available to anchor.")
    level = leaves
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [hashlib.sha256(level[i] + level[i + 1]).digest() for i in range(0, len(level), 2)]
    previous = db.scalar(select(EvidenceMerkleAnchor).where(EvidenceMerkleAnchor.workspace_id == user.workspace_id)
        .order_by(desc(EvidenceMerkleAnchor.created_at)).limit(1))
    payload = {"schema": "contexa-audit-anchor/1.0", "workspace_id": user.workspace_id,
        "leaf_count": len(leaves), "root_sha256": level[0].hex(),
        "previous_anchor_sha256": previous.root_sha256 if previous else None,
        "created_at": utcnow().isoformat()}
    signed = sign_manifest(payload)
    anchor = EvidenceMerkleAnchor(workspace_id=user.workspace_id, leaf_count=len(leaves),
        root_sha256=level[0].hex(), previous_anchor_sha256=payload["previous_anchor_sha256"],
        signing_provider=signed.provider, signing_key_id=signed.key_id,
        signature_algorithm=signed.algorithm, signature_b64=signed.signature_b64,
        payload=payload, created_by=user.id)
    db.add(anchor); db.flush()
    _audit(db, user, "audit.merkle_anchor_created", "audit_anchor", anchor.id,
        {"root_sha256": anchor.root_sha256, "leaf_count": anchor.leaf_count, "signer": signed.provider})
    db.commit(); db.refresh(anchor)
    return {"id": anchor.id, **payload, "signing_provider": signed.provider,
        "signing_key_id": signed.key_id, "signature_algorithm": signed.algorithm,
        "signature_b64": signed.signature_b64}


@router.get("/audit/anchors/{anchor_id}/verify")
def verify_audit_anchor(anchor_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    anchor = db.scalar(select(EvidenceMerkleAnchor).where(
        EvidenceMerkleAnchor.id == anchor_id,
        EvidenceMerkleAnchor.workspace_id == user.workspace_id,
    ))
    if not anchor:
        raise HTTPException(404, "Audit anchor not found.")
    fields = {
        "provider": anchor.signing_provider,
        "key_id": anchor.signing_key_id,
        "algorithm": anchor.signature_algorithm,
        "signature_b64": anchor.signature_b64,
        "manifest_sha256": hashlib.sha256(canonical_json(anchor.payload)).hexdigest(),
    }
    valid = verify_manifest(anchor.payload, fields)
    return {
        "id": anchor.id,
        "signature_valid": bool(valid),
        "root_sha256": anchor.root_sha256,
        "leaf_count": anchor.leaf_count,
        "signing_provider": anchor.signing_provider,
        "verification_method": "offline_public_key_or_local_development_key",
        "note": "This verifies the signed checkpoint payload. Independently validating individual event inclusion requires the event leaves and a Merkle inclusion proof.",
    }


def record_agent_decision(db: Session, run: AgentRun, user: User, input_value: dict, output_value: dict):
    trace = {"input": input_value, "output": output_value,
        "steps": run.steps, "agent_run_id": run.id, "document_id": run.document_id,
        "decision_boundary": "deterministic_checks_only_human_approval_required"}
    body = canonical_json(trace)
    row = DecisionTrace(workspace_id=user.workspace_id, agent_run_id=run.id,
        operation="governance_agent_run", model_id="deterministic-policy-engine",
        prompt_version="deterministic-rules-v1", input_sha256=hashlib.sha256(canonical_json(input_value)).hexdigest(),
        output_sha256=hashlib.sha256(canonical_json(output_value)).hexdigest(),
        evidence_refs=sorted(set(str(x) for check in output_value.get("fact_checks", []) for x in check.get("fact_ids", []))),
        trace=trace, integrity_sha256=hashlib.sha256(body).hexdigest(), created_by=user.id)
    db.add(row)
    return row


def attach_passport_signature_and_archive(db: Session, passport: TrustPassport, user: User):
    """Add cloud-backed signature metadata and archive canonical passport manifest."""
    signed = sign_manifest(passport.payload)
    manifest = {"payload": passport.payload, "signature": {
        "provider": signed.provider, "key_id": signed.key_id, "algorithm": signed.algorithm,
        "signature_b64": signed.signature_b64, "public_key_b64": signed.public_key_b64,
        "manifest_sha256": signed.manifest_sha256,
    }}
    archive = archive_evidence(canonical_json(manifest), f"passports/{passport.public_id}/manifest.json")
    signature_row = PassportSignature(public_id=passport.public_id, passport_id=passport.id,
        signing_provider=signed.provider, signing_key_id=signed.key_id,
        signing_algorithm=signed.algorithm, signature_b64=signed.signature_b64,
        public_key_b64=signed.public_key_b64, manifest_sha256=signed.manifest_sha256,
        verification_method="aws_kms_verify" if signed.provider == "aws_kms" else "local_hmac")
    archive_row = EvidenceArchive(workspace_id=user.workspace_id, subject_type="trust_passport",
        subject_id=passport.id, sha256=archive["sha256"], storage_uri=archive["uri"],
        storage_provider=archive["provider"], object_lock_mode=archive.get("object_lock_mode"),
        retain_until=datetime.fromisoformat(archive["retain_until"]) if archive.get("retain_until") else None,
        status="archived" if archive.get("immutable") else "stored_non_immutable", created_by=user.id)
    db.add(signature_row); db.add(archive_row)
    return signed, archive


def verify_passport_signature(db: Session, public_id: str, payload: dict[str, Any]) -> bool | None:
    row = db.get(PassportSignature, public_id)
    if not row:
        return None  # legacy HMAC passport; caller may use legacy validation
    fields = {"provider": row.signing_provider, "key_id": row.signing_key_id,
        "algorithm": row.signing_algorithm, "signature_b64": row.signature_b64,
        "public_key_b64": row.public_key_b64, "manifest_sha256": row.manifest_sha256}
    return verify_manifest(payload, fields)
