import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _run(database_url: str, *args: str):
    env = os.environ.copy()
    env.update({"APP_ENV": "test", "DATABASE_URL": database_url})
    return subprocess.run(
        [sys.executable, "bootstrap_supabase_admin.py", *args],
        cwd=BACKEND, env=env, capture_output=True, text=True, timeout=30,
    )


def test_supabase_bootstrap_creates_admin_and_member_in_same_workspace(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'supabase-bootstrap.db'}"
    env = os.environ.copy()
    env.update({"APP_ENV": "test", "DATABASE_URL": database_url})
    initialized = subprocess.run(
        [sys.executable, "-c", "from app.main import _seed; _seed()"],
        cwd=BACKEND, env=env, capture_output=True, text=True, timeout=30,
    )
    assert initialized.returncode == 0, initialized.stderr

    admin = _run(database_url, "--email", "owner@example.com", "--name", "Workspace Owner",
                  "--workspace-name", "Northstar Brand Team", "--confirm-email-verified")
    assert admin.returncode == 0, admin.stderr
    assert "Brand Admin provisioned successfully" in admin.stdout
    workspace_id = next(line.split(":", 1)[1].strip() for line in admin.stdout.splitlines()
                        if line.startswith("  Workspace ID:"))

    member = _run(database_url, "--email", "reviewer@example.com", "--name", "Legal Reviewer",
                  "--workspace-id", workspace_id, "--role", "SME / Legal", "--confirm-email-verified")
    assert member.returncode == 0, member.stderr
    assert "Role:        SME / Legal" in member.stdout
    assert f"Workspace ID:{workspace_id}" in member.stdout

    duplicate = _run(database_url, "--email", "owner@example.com", "--name", "Duplicate Owner",
                      "--workspace-name", "Another Workspace", "--confirm-email-verified")
    assert duplicate.returncode == 3
    assert "Do not create a duplicate" in duplicate.stderr


def test_supabase_bootstrap_requires_explicit_verified_email_acknowledgement(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'supabase-bootstrap-no-ack.db'}"
    result = _run(database_url, "--email", "owner@example.com", "--name", "Workspace Owner",
                  "--workspace-name", "Northstar Brand Team")
    assert result.returncode == 2
    assert "verify the email in Supabase Auth" in result.stderr
