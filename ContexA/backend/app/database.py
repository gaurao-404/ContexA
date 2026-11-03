from __future__ import annotations

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DATABASE_URL

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def prepare_database() -> None:
    if DATABASE_URL.startswith("postgresql"):
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))


# PostgreSQL RLS uses a transaction-local workspace setting. It is refreshed for
# every new transaction so pooled connections cannot retain another tenant context.
@event.listens_for(SessionLocal.class_, "after_begin")
def _apply_workspace_context(session, transaction, connection):
    workspace_id = session.info.get("workspace_id")
    if workspace_id and connection.dialect.name == "postgresql":
        connection.execute(text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
                           {"workspace_id": str(workspace_id)})


def set_workspace_context(db, workspace_id: str) -> None:
    db.info["workspace_id"] = str(workspace_id)
    if engine.dialect.name == "postgresql":
        db.execute(text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
                   {"workspace_id": str(workspace_id)})


def enable_postgres_rls() -> None:
    """Enable/force tenant policies on all workspace-owned PostgreSQL tables."""
    if engine.dialect.name != "postgresql":
        return
    policies = {
        "brand_rules": "workspace_id = current_setting('app.workspace_id', true)",
        "content_documents": "workspace_id = current_setting('app.workspace_id', true)",
        "audit_events": "workspace_id = current_setting('app.workspace_id', true)",
        "rule_versions": "workspace_id = current_setting('app.workspace_id', true)",
        "approved_facts": "workspace_id = current_setting('app.workspace_id', true)",
        "scan_runs": "workspace_id = current_setting('app.workspace_id', true)",
        "finding_evidence": "workspace_id = current_setting('app.workspace_id', true)",
        "policy_simulations": "workspace_id = current_setting('app.workspace_id', true)",
        "evaluation_cases": "workspace_id = current_setting('app.workspace_id', true)",
        "evaluation_runs": "workspace_id = current_setting('app.workspace_id', true)",
        "review_tasks": "workspace_id = current_setting('app.workspace_id', true)",
        "guideline_chunks": "workspace_id = current_setting('app.workspace_id', true)",
        "brand_assets": "workspace_id = current_setting('app.workspace_id', true)",
        "review_findings": "EXISTS (SELECT 1 FROM content_documents d WHERE d.id = content_id AND d.workspace_id = current_setting('app.workspace_id', true))",
        "monitored_sources": "workspace_id = current_setting('app.workspace_id', true)",
        "truth_drift_events": "workspace_id = current_setting('app.workspace_id', true)",
        "trust_passports": "workspace_id = current_setting('app.workspace_id', true)",
        "media_inspections": "workspace_id = current_setting('app.workspace_id', true)",
        "agent_runs": "workspace_id = current_setting('app.workspace_id', true)",
        "digital_twin_scenarios": "workspace_id = current_setting('app.workspace_id', true)",
        "language_reviews": "workspace_id = current_setting('app.workspace_id', true)",
        "regulatory_requirements": "workspace_id = current_setting('app.workspace_id', true)",
        "regulatory_assessments": "workspace_id = current_setting('app.workspace_id', true)",
        "brand_incidents": "workspace_id = current_setting('app.workspace_id', true)",
        "evidence_graph_nodes": "workspace_id = current_setting('app.workspace_id', true)",
        "evidence_graph_edges": "workspace_id = current_setting('app.workspace_id', true)",
        "decision_traces": "workspace_id = current_setting('app.workspace_id', true)",
        "evidence_archives": "workspace_id = current_setting('app.workspace_id', true)",
        "evidence_merkle_anchors": "workspace_id = current_setting('app.workspace_id', true)",
        "notifications": "workspace_id = current_setting('app.workspace_id', true)",
        "comments": "workspace_id = current_setting('app.workspace_id', true)",
        "compliance_snapshots": "workspace_id = current_setting('app.workspace_id', true)",
    }
    with engine.begin() as conn:
        for table, predicate in policies.items():
            conn.execute(text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
            conn.execute(text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))
            conn.execute(text(f'DROP POLICY IF EXISTS contexa_workspace_isolation ON "{table}"'))
            conn.execute(text(f'CREATE POLICY contexa_workspace_isolation ON "{table}" USING ({predicate}) WITH CHECK ({predicate})'))


RLS_TABLES = (
    "brand_rules", "content_documents", "audit_events", "rule_versions",
    "approved_facts", "scan_runs", "finding_evidence", "policy_simulations",
    "evaluation_cases", "evaluation_runs", "review_tasks", "guideline_chunks",
    "brand_assets", "review_findings", "monitored_sources", "truth_drift_events",
    "trust_passports", "media_inspections", "agent_runs", "digital_twin_scenarios",
    "language_reviews", "regulatory_requirements", "regulatory_assessments", "brand_incidents",
    "evidence_graph_nodes", "evidence_graph_edges", "decision_traces", "evidence_archives",
    "evidence_merkle_anchors", "notifications", "comments", "compliance_snapshots",
)

def verify_postgres_rls(require_safe_role: bool = False) -> dict[str, object]:
    """Verify forced tenant RLS is active on every workspace-owned table.

    `FORCE ROW LEVEL SECURITY` subjects the table owner to policies, but PostgreSQL
    superusers and BYPASSRLS roles always bypass them; production startup rejects
    those unsafe connection roles.
    """
    if engine.dialect.name != "postgresql":
        return {"enabled": False, "reason": "not_postgresql"}
    with engine.connect() as conn:
        role = conn.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")).mappings().one()
        unsafe_role = bool(role["rolsuper"] or role["rolbypassrls"])
        missing: list[str] = []
        missing_policies: list[str] = []
        for table in RLS_TABLES:
            row = conn.execute(text("""SELECT c.relrowsecurity, c.relforcerowsecurity
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = current_schema() AND c.relname = :table AND c.relkind = 'r'"""),
                {"table": table}).mappings().first()
            if not row or not row["relrowsecurity"] or not row["relforcerowsecurity"]:
                missing.append(table)
            policy = conn.execute(text("""SELECT qual, with_check FROM pg_policies
                WHERE schemaname = current_schema() AND tablename = :table
                  AND policyname = 'contexa_workspace_isolation'"""),
                {"table": table}).mappings().first()
            if (not policy or not policy["qual"] or not policy["with_check"]
                    or "app.workspace_id" not in str(policy["qual"])
                    or "app.workspace_id" not in str(policy["with_check"])):
                missing_policies.append(table)
    if missing:
        raise RuntimeError("PostgreSQL tenant RLS is missing or not forced for: " + ", ".join(missing))
    if missing_policies:
        raise RuntimeError("PostgreSQL workspace isolation policies are missing: " + ", ".join(missing_policies))
    if require_safe_role and unsafe_role:
        raise RuntimeError("Production database role is superuser or has BYPASSRLS. Use a non-superuser application role; FORCE RLS cannot constrain these roles.")
    return {"enabled": True, "forced_tables": list(RLS_TABLES), "policy_tables": list(RLS_TABLES), "unsafe_role": unsafe_role}
