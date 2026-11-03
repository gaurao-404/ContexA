#!/usr/bin/env python3
"""Read-only smoke check for ContexA's least-privilege Supabase session reader."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import create_engine, text  # noqa: E402
from app.config import SUPABASE_SESSION_DATABASE_URL  # noqa: E402


def main() -> int:
    if not SUPABASE_SESSION_DATABASE_URL:
        raise SystemExit("SUPABASE_SESSION_DATABASE_URL is not configured.")
    if not SUPABASE_SESSION_DATABASE_URL.startswith("postgresql+"):
        raise SystemExit("SUPABASE_SESSION_DATABASE_URL must use the PostgreSQL psycopg driver.")
    engine = create_engine(SUPABASE_SESSION_DATABASE_URL, pool_pre_ping=True, pool_size=1, max_overflow=0)
    try:
        with engine.connect() as connection:
            role = connection.scalar(text("SELECT current_user"))
            flags = connection.execute(text(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
            )).mappings().one()
            view_exists = connection.scalar(text(
                "SELECT to_regclass('contexa_private.active_auth_sessions') IS NOT NULL"
            ))
            # Count is sufficient to validate SELECT permission; never print IDs or user data.
            connection.scalar(text("SELECT count(*) FROM contexa_private.active_auth_sessions"))
        if role != "contexa_session_reader":
            raise RuntimeError("Connection must use the contexa_session_reader role.")
        if flags["rolsuper"] or flags["rolbypassrls"]:
            raise RuntimeError("Session reader must not be superuser or BYPASSRLS.")
        if not view_exists:
            raise RuntimeError("The private active_auth_sessions view is missing.")
        print("PASS: Supabase session-reader connection succeeded.")
        print("PASS: role is non-superuser and NOBYPASSRLS.")
        print("PASS: private session projection is readable.")
        print("NOTE: this confirms database permissions only; verify real sign-out/revocation with a test user.")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
