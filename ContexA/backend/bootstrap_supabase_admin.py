"""Provision the first ContexA workspace admin for an already-verified Supabase user.

Run from the backend directory after the production database schema is migrated:
  python bootstrap_supabase_admin.py --email admin@example.com --name "Admin Name" \
    --workspace-name "Acme Brand Team" --confirm-email-verified

This command intentionally does not call Supabase Admin APIs and never needs a
service-role key. Create/verify the identity in Supabase Dashboard first. The first
successful ContexA API request links the Supabase subject to this existing record.
"""
from __future__ import annotations

import argparse
import secrets
import sys
import uuid
from pathlib import Path

# Support execution from the repository root as well as backend/.
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal, set_workspace_context  # noqa: E402
from app.main import _audit, _ensure_rule_versions, _seed_workspace_rules  # noqa: E402
from app.models import User, utcnow  # noqa: E402
from app.security import hash_password  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create the initial ContexA Brand Admin mapped to a verified Supabase identity.")
    parser.add_argument("--email", required=True, help="Email address exactly matching the verified Supabase Auth user")
    parser.add_argument("--name", required=True, help="Administrator display name")
    parser.add_argument("--workspace-name", help="Workspace name (required when creating a new workspace)")
    parser.add_argument("--workspace-id", help="Existing workspace ID when provisioning an additional member")
    parser.add_argument("--role", choices=["Brand Admin", "Manager", "SME / Legal", "Creator"], default="Brand Admin")
    parser.add_argument("--supabase-subject", help="Optional Supabase Auth user UUID; otherwise linked on first verified sign-in by email")
    parser.add_argument("--confirm-email-verified", action="store_true", help="Required acknowledgement that email_confirmed_at is set in Supabase Auth")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    email = args.email.strip().lower()
    name = " ".join(args.name.split())
    workspace_name = " ".join((args.workspace_name or "").split())
    if not args.confirm_email_verified:
        print("Refusing to provision: verify the email in Supabase Auth, then pass --confirm-email-verified.", file=sys.stderr)
        return 2
    if len(name) < 2 or "@" not in email:
        print("Enter a valid email and name.", file=sys.stderr)
        return 2
    if not args.workspace_id and len(workspace_name) < 2:
        print("--workspace-name is required when creating a new workspace.", file=sys.stderr)
        return 2
    subject = args.supabase_subject.strip() if args.supabase_subject else None
    if subject:
        try:
            subject = str(uuid.UUID(subject))
        except ValueError:
            print("--supabase-subject must be a UUID from Supabase Authentication → Users.", file=sys.stderr)
            return 2

    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.email == email))
        if existing:
            if existing.supabase_subject:
                print(f"A ContexA account is already linked for {email}; no changes made.", file=sys.stderr)
                return 3
            print(
                f"A ContexA account already exists for {email}. Do not create a duplicate. "
                "Sign in with the verified Supabase identity to link it, or ask an administrator to review the existing role/workspace.",
                file=sys.stderr,
            )
            return 3
        if subject and db.scalar(select(User.id).where(User.supabase_subject == subject)):
            print("That Supabase subject is already linked to another ContexA account.", file=sys.stderr)
            return 3

        if args.workspace_id:
            workspace_id = args.workspace_id.strip()
            owner_or_member = db.scalar(select(User).where(User.workspace_id == workspace_id).limit(1))
            if not owner_or_member:
                print("No existing ContexA workspace was found for --workspace-id.", file=sys.stderr)
                return 3
            resolved_workspace_name = workspace_name[:140] or owner_or_member.workspace_name
            role = args.role
        else:
            workspace_id = f"ws-{uuid.uuid4()}"
            resolved_workspace_name = workspace_name[:140]
            role = "Brand Admin"
        set_workspace_context(db, workspace_id)
        # Supabase is the accepted authentication path in this profile. This
        # random password hash is not a usable password and is never returned.
        user = User(
            name=name,
            email=email,
            role=role,
            workspace_id=workspace_id,
            workspace_name=resolved_workspace_name,
            password_hash=hash_password(secrets.token_urlsafe(64)),
            is_active=True,
            is_email_verified=True,
            email_verified_at=utcnow(),
            supabase_subject=subject,
        )
        db.add(user)
        db.flush()
        if not args.workspace_id:
            _seed_workspace_rules(db, workspace_id)
            _ensure_rule_versions(db, workspace_id)
        _audit(db, user, "identity.supabase_member_provisioned", "user", user.id, {
            "email": email,
            "workspace_name": resolved_workspace_name,
            "provider": "supabase",
            "role": role,
            "subject_prelinked": bool(subject),
        })
        db.commit()
        print("ContexA Brand Admin provisioned successfully.")
        print(f"  Email:       {email}")
        print(f"  Role:        {role}")
        print(f"  Workspace:   {resolved_workspace_name}")
        print(f"  Workspace ID:{workspace_id}")
        print("  Next: sign in through the Supabase-enabled ContexA login screen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
