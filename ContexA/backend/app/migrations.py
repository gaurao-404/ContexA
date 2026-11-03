"""Small, idempotent schema migration runner for ContexA's additive releases.

This project uses SQLAlchemy metadata as the canonical portable schema. The runner
creates missing tables/indexes and records each release migration. Existing table
alterations continue to use the explicit legacy compatibility steps in main.py.
For production deployments, take a PostgreSQL backup before applying a release.
"""
from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import MetaData, Table, Column, String, DateTime, select, insert, text
from sqlalchemy.engine import Engine

from .database import Base

TRUST_OS_MIGRATIONS = (
    "2026_11_01_01_trust_os_capabilities",
    "2026_11_01_02_public_passport_index",
    "2026_11_01_03_enterprise_trust_foundation",
    "2026_11_01_04_collaboration_analytics_indexes",
)

# Hot-path composite indexes. IF NOT EXISTS keeps this portable and idempotent.
PERFORMANCE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_docs_ws_status_updated ON content_documents (workspace_id, status, updated_at)",
    "CREATE INDEX IF NOT EXISTS ix_findings_content_status_sev ON review_findings (content_id, status, severity)",
    "CREATE INDEX IF NOT EXISTS ix_audit_ws_created ON audit_events (workspace_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_audit_ws_entity ON audit_events (workspace_id, entity_type, entity_id)",
    "CREATE INDEX IF NOT EXISTS ix_tasks_ws_status ON review_tasks (workspace_id, status, priority)",
    "CREATE INDEX IF NOT EXISTS ix_notifications_user_unread ON notifications (user_id, read_at, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_comments_entity ON comments (workspace_id, entity_type, entity_id, created_at)",
)


def run_migrations(engine: Engine) -> list[str]:
    metadata = MetaData()
    versions = Table(
        "schema_migrations", metadata,
        Column("version", String(100), primary_key=True),
        Column("applied_at", DateTime(timezone=True), nullable=False),
    )
    metadata.create_all(engine, tables=[versions], checkfirst=True)
    with engine.begin() as connection:
        applied = set(connection.execute(select(versions.c.version)).scalars().all())
    pending = [version for version in TRUST_OS_MIGRATIONS if version not in applied]
    completed: list[str] = []
    for version in pending:
        # create_all is intentionally idempotent and portable across SQLite/PostgreSQL.
        # Each additive release records its own version; new metadata objects are
        # created even when an earlier Trust OS release was already applied.
        Base.metadata.create_all(engine, checkfirst=True)
        with engine.begin() as connection:
            if version == "2026_11_01_03_enterprise_trust_foundation":
                # Add external identity link to existing users table without losing local accounts.
                inspector_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(users)").all()} if connection.dialect.name == "sqlite" else {row["name"] for row in connection.exec_driver_sql("SELECT column_name AS name FROM information_schema.columns WHERE table_name='users' AND table_schema=current_schema()").mappings().all()}
                if "supabase_subject" not in inspector_columns:
                    connection.exec_driver_sql("ALTER TABLE users ADD COLUMN supabase_subject VARCHAR(128)")
                connection.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_supabase_subject ON users (supabase_subject)")
            if version == "2026_11_01_02_public_passport_index":
                # Backfill public indexes for passports issued before this release.
                # On PostgreSQL, the workspace context is set one tenant at a time
                # so FORCE RLS remains enabled and no superuser/bypass role is needed.
                users = Base.metadata.tables["users"]
                passports = Base.metadata.tables["trust_passports"]
                public_index = Base.metadata.tables["public_passport_index"]
                workspaces = connection.execute(select(users.c.workspace_id).distinct()).scalars().all()
                for workspace_id in workspaces:
                    if connection.dialect.name == "postgresql":
                        connection.execute(text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
                                           {"workspace_id": str(workspace_id)})
                    rows = connection.execute(select(
                        passports.c.public_id, passports.c.id, passports.c.title,
                        passports.c.asset_sha256, passports.c.payload, passports.c.signature,
                        passports.c.status, passports.c.issued_at, passports.c.revoked_at,
                    ).where(passports.c.workspace_id == workspace_id)).mappings().all()
                    for row in rows:
                        exists = connection.execute(select(public_index.c.public_id).where(
                            public_index.c.public_id == row["public_id"])).scalar_one_or_none()
                        if not exists:
                            connection.execute(insert(public_index).values(
                                public_id=row["public_id"], passport_id=row["id"], title=row["title"],
                                asset_sha256=row["asset_sha256"], payload=row["payload"],
                                signature=row["signature"], status=row["status"],
                                issued_at=row["issued_at"], revoked_at=row["revoked_at"],
                            ))
            if version == "2026_11_01_04_collaboration_analytics_indexes":
                for statement in PERFORMANCE_INDEXES:
                    connection.exec_driver_sql(statement)
            connection.execute(insert(versions).values(
                version=version,
                applied_at=datetime.now(timezone.utc),
            ))
        completed.append(version)
    return completed
