#!/usr/bin/env python3
"""Verify forced tenant RLS metadata and read isolation using the app DB role."""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import text  # noqa: E402
from app.database import engine, verify_postgres_rls  # noqa: E402


def main() -> int:
    if engine.dialect.name != "postgresql":
        raise SystemExit("DATABASE_URL must point to PostgreSQL for this check.")
    result = verify_postgres_rls(require_safe_role=True)
    print(f"RLS metadata passed for {len(result['forced_tables'])} tables; application role is not superuser/BYPASSRLS.")

    suffix = uuid.uuid4().hex[:12]
    workspace_a = f"rls-check-a-{suffix}"
    workspace_b = f"rls-check-b-{suffix}"
    id_a, id_b = str(uuid.uuid4()), str(uuid.uuid4())
    base_sql = """INSERT INTO brand_rules
        (id, workspace_id, code, title, category, rule_clause, source_document,
         severity, suggested_fix, is_active, embedding_model)
        VALUES (:id, :wid, :code, 'RLS verification sentinel', 'test',
         'Temporary RLS isolation verification row.', 'ops/verify_postgres_rls.py',
         'info', 'No action', TRUE, 'hashed-token-v1')"""
    try:
        with engine.begin() as conn:
            conn.execute(text("SELECT set_config('app.workspace_id', :wid, true)"), {"wid": workspace_a})
            conn.execute(text(base_sql), {"id": id_a, "wid": workspace_a, "code": f"RLSA-{suffix}"})
            conn.execute(text("SELECT set_config('app.workspace_id', :wid, true)"), {"wid": workspace_b})
            conn.execute(text(base_sql), {"id": id_b, "wid": workspace_b, "code": f"RLSB-{suffix}"})

            conn.execute(text("SELECT set_config('app.workspace_id', :wid, true)"), {"wid": workspace_a})
            visible_a = conn.scalar(text("SELECT count(*) FROM brand_rules WHERE id IN (:a,:b)"), {"a": id_a, "b": id_b})
            if visible_a != 1 or conn.scalar(text("SELECT count(*) FROM brand_rules WHERE id=:id"), {"id": id_a}) != 1:
                raise RuntimeError("Workspace A could not see exactly its own sentinel row.")

            conn.execute(text("SELECT set_config('app.workspace_id', :wid, true)"), {"wid": workspace_b})
            visible_b = conn.scalar(text("SELECT count(*) FROM brand_rules WHERE id IN (:a,:b)"), {"a": id_a, "b": id_b})
            if visible_b != 1 or conn.scalar(text("SELECT count(*) FROM brand_rules WHERE id=:id"), {"id": id_b}) != 1:
                raise RuntimeError("Workspace B could not see exactly its own sentinel row.")

            conn.execute(text("SELECT set_config('app.workspace_id', :wid, true)"), {"wid": workspace_a})
            conn.execute(text("DELETE FROM brand_rules WHERE id=:id"), {"id": id_a})
            conn.execute(text("SELECT set_config('app.workspace_id', :wid, true)"), {"wid": workspace_b})
            conn.execute(text("DELETE FROM brand_rules WHERE id=:id"), {"id": id_b})
    except Exception:
        # The transaction rolls back if verification fails; sentinel IDs are unique.
        raise
    print("RLS isolation passed: each workspace saw only its own sentinel row; temporary rows were removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
