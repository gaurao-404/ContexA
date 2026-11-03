from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR.parent / ".env")

APP_NAME = "ContexA API"
APP_ENV = os.getenv("APP_ENV", "development")
_raw_database_url = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'contexa.db'}")
# Render and several managed providers expose postgres:// or postgresql:// URLs; use
# SQLAlchemy's explicitly installed psycopg v3 driver instead of assuming psycopg2.
if _raw_database_url.startswith("postgres://"):
    DATABASE_URL = "postgresql+psycopg://" + _raw_database_url[len("postgres://"):]
elif _raw_database_url.startswith("postgresql://"):
    DATABASE_URL = "postgresql+psycopg://" + _raw_database_url[len("postgresql://"):]
else:
    DATABASE_URL = _raw_database_url
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", str(BASE_DIR / "storage"))).resolve()
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-this-secret-before-deploying")
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "720"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "35"))
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
# Optional Cloudflare AI Gateway proxy for observable, centrally managed Claude calls.
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "").rstrip("/")
CLOUDFLARE_AI_GATEWAY_TOKEN = os.getenv("CLOUDFLARE_AI_GATEWAY_TOKEN", "")
# Local-first contextual AI. Ollama runs on the user’s machine and needs no cloud API key.
OLLAMA_ENABLED = os.getenv("OLLAMA_ENABLED", "false").lower() in {"1", "true", "yes"}
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "nemotron-mini:4b")
OLLAMA_REQUEST_TIMEOUT = float(os.getenv("OLLAMA_REQUEST_TIMEOUT", "60"))
WORKSPACE_ID = os.getenv("WORKSPACE_ID", "ws-contexa-demo")
ENABLE_POSTGRES_RLS = os.getenv("ENABLE_POSTGRES_RLS", "true").lower() in {"1", "true", "yes"}
ALLOW_SIGNUP = os.getenv("ALLOW_SIGNUP", "true").lower() in {"1", "true", "yes"}
STORE_UPLOADS_IN_DATABASE = os.getenv("STORE_UPLOADS_IN_DATABASE", "false").lower() in {"1", "true", "yes"}
AI_VERIFICATION_ENABLED = os.getenv("AI_VERIFICATION_ENABLED", "false").lower() in {"1", "true", "yes"}

# Optional email delivery for account verification, invitations and password recovery.
EMAIL_VERIFICATION_REQUIRED = os.getenv("EMAIL_VERIFICATION_REQUIRED", "false").lower() in {"1", "true", "yes"}
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "ContexA Studio")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() in {"1", "true", "yes"}
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "false").lower() in {"1", "true", "yes"}
PUBLIC_APP_URL = os.getenv("PUBLIC_APP_URL", "http://localhost:5173").rstrip("/")
AUTH_TOKEN_MINUTES = int(os.getenv("AUTH_TOKEN_MINUTES", "45"))
LOGIN_MAX_FAILURES = int(os.getenv("LOGIN_MAX_FAILURES", "8"))
LOGIN_LOCK_MINUTES = int(os.getenv("LOGIN_LOCK_MINUTES", "15"))
UPLOAD_SCAN_MODE = os.getenv("UPLOAD_SCAN_MODE", "disabled").lower()
CLAMD_HOST = os.getenv("CLAMD_HOST", "127.0.0.1")
CLAMD_PORT = int(os.getenv("CLAMD_PORT", "3310"))

# Optional local semantic embeddings. Keep disabled for portable submission/demo mode.
OLLAMA_EMBEDDINGS_ENABLED = os.getenv("OLLAMA_EMBEDDINGS_ENABLED", "false").lower() in {"1", "true", "yes"}
OLLAMA_EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
OLLAMA_EMBEDDING_TIMEOUT = float(os.getenv("OLLAMA_EMBEDDING_TIMEOUT", "25"))

# Optional private S3-compatible object storage (S3, R2, MinIO, etc.).
S3_BUCKET = os.getenv("S3_BUCKET", "")
S3_REGION = os.getenv("S3_REGION", "ap-south-1")
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "")
S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID", "")
S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY", "")
S3_PREFIX = os.getenv("S3_PREFIX", "contexa")
S3_FORCE_PATH_STYLE = os.getenv("S3_FORCE_PATH_STYLE", "false").lower() in {"1", "true", "yes"}

SIGNUP_MAX_PER_IP = int(os.getenv("SIGNUP_MAX_PER_IP", "25"))
SIGNUP_WINDOW_MINUTES = int(os.getenv("SIGNUP_WINDOW_MINUTES", "60"))
PASSWORD_RESET_MAX_PER_IP = int(os.getenv("PASSWORD_RESET_MAX_PER_IP", "5"))
UPLOAD_MAX_PER_USER = int(os.getenv("UPLOAD_MAX_PER_USER", "40"))
UPLOAD_WINDOW_MINUTES = int(os.getenv("UPLOAD_WINDOW_MINUTES", "60"))

S3_SERVER_SIDE_ENCRYPTION = os.getenv("S3_SERVER_SIDE_ENCRYPTION", "")
REQUIRE_PRIVATE_OBJECT_STORAGE = os.getenv("REQUIRE_PRIVATE_OBJECT_STORAGE", "false").lower() in {"1", "true", "yes"}
REQUIRE_MALWARE_SCAN = os.getenv("REQUIRE_MALWARE_SCAN", "false").lower() in {"1", "true", "yes"}

SECURITY_HEADERS_ENABLED = os.getenv("SECURITY_HEADERS_ENABLED", "true").lower() in {"1", "true", "yes"}

# Optional Cloudflare application security integrations. Turnstile is enforced
# server-side whenever a secret is configured; an unconfigured local demo remains frictionless.
TURNSTILE_SECRET_KEY = os.getenv("TURNSTILE_SECRET_KEY", "")
TURNSTILE_EXPECTED_HOSTNAME = os.getenv("TURNSTILE_EXPECTED_HOSTNAME", "").strip().lower()
CLOUDFLARE_EDGE_ENABLED = os.getenv("CLOUDFLARE_EDGE_ENABLED", "false").lower() in {"1", "true", "yes"}
CLOUDFLARE_ORIGIN_SHARED_SECRET = os.getenv("CLOUDFLARE_ORIGIN_SHARED_SECRET", "")
PUBLIC_API_URL = os.getenv("PUBLIC_API_URL", "").rstrip("/")

AUTH_TOKEN_RETENTION_DAYS = int(os.getenv("AUTH_TOKEN_RETENTION_DAYS", "30"))
LOGIN_ATTEMPT_RETENTION_DAYS = int(os.getenv("LOGIN_ATTEMPT_RETENTION_DAYS", "90"))

# Use a dedicated stable secret for passport signatures so routine auth-secret rotation can be managed separately.
TRUST_PASSPORT_SIGNING_KEY = os.getenv("TRUST_PASSPORT_SIGNING_KEY", SECRET_KEY)
TRUTH_DRIFT_CRON_TOKEN = os.getenv("TRUTH_DRIFT_CRON_TOKEN", "")


# Optional external identity provider. Local auth remains the backward-compatible default.
AUTH_MODE = os.getenv("AUTH_MODE", "local").strip().lower()  # local | hybrid | supabase
SUPABASE_AUTH_ENABLED = AUTH_MODE in {"hybrid", "supabase"}
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_JWT_ISSUER = os.getenv("SUPABASE_JWT_ISSUER", f"{SUPABASE_URL}/auth/v1" if SUPABASE_URL else "").rstrip("/")
SUPABASE_JWKS_URL = os.getenv("SUPABASE_JWKS_URL", f"{SUPABASE_JWT_ISSUER}/.well-known/jwks.json" if SUPABASE_JWT_ISSUER else "")
SUPABASE_JWT_AUDIENCE = os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated")
SUPABASE_JWT_ALGORITHMS = [x.strip().upper() for x in os.getenv("SUPABASE_JWT_ALGORITHMS", "ES256,RS256").split(",") if x.strip()]
# Additional strict origins permitted by the browser CSP connect-src directive.
CSP_EXTRA_CONNECT_ORIGINS = os.getenv("CSP_EXTRA_CONNECT_ORIGINS", "")
SUPABASE_REQUIRE_AAL2 = os.getenv("SUPABASE_REQUIRE_AAL2", "false").lower() in {"1", "true", "yes"}
# Optional direct PostgreSQL connection to the same Supabase project. It is used
# only to check auth.sessions existence for immediate sign-out revocation; never
# place this connection string in a browser-visible VITE_* variable.
_raw_supabase_session_database_url = os.getenv("SUPABASE_SESSION_DATABASE_URL", "").strip()
if _raw_supabase_session_database_url.startswith("postgres://"):
    SUPABASE_SESSION_DATABASE_URL = "postgresql+psycopg://" + _raw_supabase_session_database_url[len("postgres://"):]
elif _raw_supabase_session_database_url.startswith("postgresql://"):
    SUPABASE_SESSION_DATABASE_URL = "postgresql+psycopg://" + _raw_supabase_session_database_url[len("postgresql://"):]
else:
    SUPABASE_SESSION_DATABASE_URL = _raw_supabase_session_database_url
SUPABASE_SESSION_CHECK_REQUIRED = os.getenv(
    "SUPABASE_SESSION_CHECK_REQUIRED",
    "true" if AUTH_MODE in {"hybrid", "supabase"} else "false",
).lower() in {"1", "true", "yes"}
# Publishable key is public/browser-safe but also needed by the backend when it
# asks Supabase Auth to revoke the current session during /api/auth/logout.
SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", os.getenv("SUPABASE_ANON_KEY", "")).strip()

# AWS uses workload identity (ECS task role / IAM role) by default. Do not store
# long-lived AWS access keys in application environment variables.
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
TRUST_SIGNING_PROVIDER = os.getenv("TRUST_SIGNING_PROVIDER", "local_hmac").strip().lower()  # local_hmac | aws_kms
TRUST_KMS_KEY_ID = os.getenv("TRUST_KMS_KEY_ID", "")
TRUST_KMS_SIGNING_ALGORITHM = os.getenv("TRUST_KMS_SIGNING_ALGORITHM", "RSASSA_PSS_SHA_256")
EVIDENCE_ARCHIVE_BUCKET = os.getenv("EVIDENCE_ARCHIVE_BUCKET", "")
EVIDENCE_ARCHIVE_PREFIX = os.getenv("EVIDENCE_ARCHIVE_PREFIX", "contexa-evidence")
EVIDENCE_ARCHIVE_RETENTION_DAYS = int(os.getenv("EVIDENCE_ARCHIVE_RETENTION_DAYS", "0"))
EVIDENCE_ARCHIVE_MODE = os.getenv("EVIDENCE_ARCHIVE_MODE", "COMPLIANCE").upper()
EVIDENCE_ARCHIVE_SSE = os.getenv("EVIDENCE_ARCHIVE_SSE", "aws:kms" if os.getenv("EVIDENCE_ARCHIVE_KMS_KEY_ID") else "AES256")
EVIDENCE_ARCHIVE_KMS_KEY_ID = os.getenv("EVIDENCE_ARCHIVE_KMS_KEY_ID", "")
TRUST_ARCHIVE_REQUIRED = os.getenv("TRUST_ARCHIVE_REQUIRED", "false").lower() in {"1", "true", "yes"}
