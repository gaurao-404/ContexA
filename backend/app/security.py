from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import ACCESS_TOKEN_MINUTES, SECRET_KEY
from .database import get_db
from .models import User

bearer = HTTPBearer(auto_error=False)


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 240_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, digest = stored.split("$", 2)
        if scheme != "pbkdf2_sha256":
            return False
        actual = hash_password(password, salt).split("$", 2)[2]
        return hmac.compare_digest(actual, digest)
    except (ValueError, TypeError):
        return False


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def create_access_token(user: User) -> str:
    now = int(time.time())
    payload = {"sub": user.id, "email": user.email, "role": user.role,
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
    payload = decode_access_token(credentials.credentials)
    user = db.get(User, payload["sub"])
    if not user or user.is_active is False:
        raise HTTPException(status_code=401, detail="This account is inactive.")
    return user


def require_roles(*roles: str):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail=f"This action requires one of: {', '.join(roles)}.")
        return user
    return dependency
