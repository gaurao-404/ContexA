from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any
from uuid import UUID
from urllib.request import Request as URLRequest, urlopen

from sqlalchemy import create_engine, text

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError, InvalidHashError
    _ARGON2 = PasswordHasher(time_cost=3, memory_cost=32768, parallelism=1, hash_len=32, salt_len=16)
except ImportError:  # fallback keeps constrained offline installs functional
    _ARGON2 = None
    VerifyMismatchError = InvalidHashError = ValueError
from sqlalchemy.orm import Session

from .config import (ACCESS_TOKEN_MINUTES, SECRET_KEY, AUTH_MODE, SUPABASE_JWKS_URL,
                     SUPABASE_JWT_ISSUER, SUPABASE_JWT_AUDIENCE, SUPABASE_JWT_ALGORITHMS, SUPABASE_REQUIRE_AAL2,
                     SUPABASE_SESSION_DATABASE_URL, SUPABASE_SESSION_CHECK_REQUIRED,
                     SUPABASE_PUBLISHABLE_KEY, SUPABASE_URL)
from .database import get_db, set_workspace_context
from .models import User, utcnow

_SUPABASE_JWKS_CLIENT = None
_SUPABASE_SESSION_ENGINE = None

def revoke_supabase_session(access_token: str) -> None:
    """Revoke only the caller's current Supabase Auth session via the Auth API."""
    if not SUPABASE_URL or not SUPABASE_PUBLISHABLE_KEY:
        raise HTTPException(status_code=503, detail="Supabase sign-out is not configured; session revocation was not confirmed.")
    request = URLRequest(
        f"{SUPABASE_URL}/auth/v1/logout?scope=local",
        data=b"{}",
        headers={
            "apikey": SUPABASE_PUBLISHABLE_KEY,
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=12) as response:
            if response.status not in {200, 204}:
                raise RuntimeError(f"Unexpected Supabase sign-out status: {response.status}")
    except Exception as exc:
        # Keep access tokens and credentials out of logs and error bodies.
        raise HTTPException(status_code=503, detail="Supabase could not confirm sign-out; please retry.") from exc


def _require_active_supabase_session(payload: dict[str, Any]) -> None:
    """Fail closed when immediate Supabase sign-out revocation is required.

    Supabase's Auth session row is deleted when a session signs out. Checking the
    row on each API request prevents an already-issued, unexpired JWT from
    remaining valid in ContexA after sign-out. This connection must target the
    *same Supabase project* that issued the token and use a server-only database
    credential with read access to auth.sessions.
    """
    global _SUPABASE_SESSION_ENGINE
    if not SUPABASE_SESSION_CHECK_REQUIRED:
        return
    if not SUPABASE_SESSION_DATABASE_URL:
        raise HTTPException(
            status_code=503,
            detail="Supabase session revocation is required but SUPABASE_SESSION_DATABASE_URL is not configured.",
        )
    try:
        session_id = str(UUID(str(payload.get("session_id", ""))))
        user_id = str(UUID(str(payload.get("sub", ""))))
    except (TypeError, ValueError, AttributeError) as exc:
        raise HTTPException(status_code=401, detail="Supabase token is missing a valid session identity.") from exc
    try:
        if _SUPABASE_SESSION_ENGINE is None:
            if not SUPABASE_SESSION_DATABASE_URL.startswith("postgresql+"):
                raise ValueError("SUPABASE_SESSION_DATABASE_URL must use the PostgreSQL psycopg driver.")
            _SUPABASE_SESSION_ENGINE = create_engine(
                SUPABASE_SESSION_DATABASE_URL,
                pool_pre_ping=True,
                pool_size=2,
                max_overflow=2,
                pool_recycle=300,
            )
        with _SUPABASE_SESSION_ENGINE.connect() as connection:
            active = connection.scalar(text("""
                SELECT 1
                FROM contexa_private.active_auth_sessions
                WHERE id = CAST(:session_id AS uuid)
                  AND user_id = CAST(:user_id AS uuid)
                LIMIT 1
            """), {"session_id": session_id, "user_id": user_id})
    except Exception as exc:
        # Do not log connection strings, JWTs or database credentials.
        raise HTTPException(
            status_code=503,
            detail="Supabase session status could not be verified; access is temporarily blocked.",
        ) from exc
    if active != 1:
        raise HTTPException(status_code=401, detail="This Supabase session has been revoked. Please sign in again.")


def decode_supabase_access_token(token: str) -> dict[str, Any]:
    """Verify an asymmetric Supabase Auth JWT against the project's JWKS.

    User-controlled metadata is never used for workspace or role authorization.
    """
    global _SUPABASE_JWKS_CLIENT
    if not (SUPABASE_JWKS_URL and SUPABASE_JWT_ISSUER):
        raise HTTPException(status_code=503, detail="Supabase Auth is enabled but issuer/JWKS configuration is incomplete.")
    # Supabase recommends asymmetric signing keys for server-side verification.
    # Never silently accept HS256/shared-secret signing in this integration.
    supported_algorithms = {"ES256", "RS256"}
    if not SUPABASE_JWT_ALGORITHMS or not set(SUPABASE_JWT_ALGORITHMS).issubset(supported_algorithms):
        raise HTTPException(status_code=503, detail="Configure only asymmetric ES256 or RS256 Supabase JWT signing algorithms.")
    try:
        import jwt
        if _SUPABASE_JWKS_CLIENT is None:
            _SUPABASE_JWKS_CLIENT = jwt.PyJWKClient(SUPABASE_JWKS_URL, cache_keys=True)
        signing_key = _SUPABASE_JWKS_CLIENT.get_signing_key_from_jwt(token)
        payload = jwt.decode(token, signing_key.key, algorithms=SUPABASE_JWT_ALGORITHMS,
            audience=SUPABASE_JWT_AUDIENCE, issuer=SUPABASE_JWT_ISSUER,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]})
        if not payload.get("sub") or not payload.get("email"):
            raise ValueError("Required Supabase identity claims are missing.")
        if payload.get("email_verified") is not True:
            raise ValueError("Supabase email identity is not verified.")
        if SUPABASE_REQUIRE_AAL2 and payload.get("aal") != "aal2":
            raise ValueError("This workspace requires a recent MFA-authenticated session (AAL2).")
        _require_active_supabase_session(payload)
        return payload
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid Supabase session. Please sign in again.") from exc

bearer = HTTPBearer(auto_error=False)


def hash_password(password: str, salt: str | None = None) -> str:
    """Hash new passwords with Argon2id; retain PBKDF2 fallback for minimal installations."""
    if _ARGON2 is not None and salt is None:
        return _ARGON2.hash(password)
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 240_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    if stored.startswith("$argon2") and _ARGON2 is not None:
        try:
            return _ARGON2.verify(stored, password)
        except (VerifyMismatchError, InvalidHashError, ValueError):
            return False
    try:
        scheme, salt, digest = stored.split("$", 2)
        if scheme != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 240_000).hex()
        return hmac.compare_digest(actual, digest)
    except (ValueError, TypeError):
        return False


def password_needs_rehash(stored: str) -> bool:
    return bool(_ARGON2 is not None and not stored.startswith("$argon2"))

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def create_access_token(user: User) -> str:
    now = int(time.time())
    payload = {"sub": user.id, "email": user.email, "role": user.role,
               "workspace_id": user.workspace_id, "tv": int(getattr(user, "token_version", 0) or 0),
               "iat": now, "exp": now + ACCESS_TOKEN_MINUTES * 60}
    raw = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = _b64(hmac.new(SECRET_KEY.encode(), raw.encode(), hashlib.sha256).digest())
    return f"{raw}.{signature}"


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        raw, signature = token.split(".", 1)
        expected = _b64(hmac.new(SECRET_KEY.encode(), raw.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("bad signature")
        padded = raw + "=" * (-len(raw) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        if int(payload.get("exp", 0)) < int(time.time()):
            raise ValueError("expired")
        if not payload.get("sub"):
            raise ValueError("missing subject")
        return payload
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session. Please sign in again.") from exc


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    raw_token = credentials.credentials
    is_standard_jwt = raw_token.count(".") == 2
    use_supabase = AUTH_MODE == "supabase" or (AUTH_MODE == "hybrid" and is_standard_jwt)
    if AUTH_MODE == "supabase" and not is_standard_jwt:
        raise HTTPException(status_code=401, detail="Sign in through the configured Supabase identity provider.")
    if use_supabase:
        payload = decode_supabase_access_token(raw_token)
        subject = str(payload["sub"])
        email = str(payload["email"]).strip().lower()
        user = db.query(User).filter(User.supabase_subject == subject).one_or_none()
        if user is None:
            # Link only to an existing ContexA identity whose email matches a verified
            # provider claim. Never provision a new workspace from arbitrary JWT metadata.
            user = db.query(User).filter(User.email == email).one_or_none()
            if user is None:
                raise HTTPException(status_code=403, detail="No ContexA account matches this verified identity. Ask a workspace administrator for an invitation.")
            if user.supabase_subject and user.supabase_subject != subject:
                raise HTTPException(status_code=409, detail="This ContexA account is already linked to another external identity.")
            user.supabase_subject = subject
            user.is_email_verified = True
            user.email_verified_at = user.email_verified_at or utcnow()
            db.commit()
        if user.is_active is False:
            raise HTTPException(status_code=401, detail="This account is inactive.")
        if user.email.lower() != email:
            raise HTTPException(status_code=401, detail="The external identity email no longer matches the linked ContexA account.")
        set_workspace_context(db, user.workspace_id)
        return user

    payload = decode_access_token(raw_token)
    # Only ContexA-signed local tokens may provide the workspace claim used to prime RLS.
    claimed_workspace = payload.get("workspace_id")
    if claimed_workspace:
        set_workspace_context(db, claimed_workspace)
    user = db.get(User, payload["sub"])
    if not user or user.is_active is False:
        raise HTTPException(status_code=401, detail="This account is inactive.")
    if int(payload.get("tv", 0)) != int(getattr(user, "token_version", 0) or 0):
        raise HTTPException(status_code=401, detail="This session has been revoked. Please sign in again.")
    if claimed_workspace and user.workspace_id != claimed_workspace:
        raise HTTPException(status_code=401, detail="The session workspace no longer matches this account.")
    set_workspace_context(db, user.workspace_id)
    return user


def require_roles(*roles: str):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail=f"This action requires one of: {', '.join(roles)}.")
        return user
    return dependency
