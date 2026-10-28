from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR.parent / ".env")

APP_NAME = "ContexA API"
APP_ENV = os.getenv("APP_ENV", "development")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'contexa.db'}")
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", str(BASE_DIR / "storage"))).resolve()
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-this-secret-before-deploying")
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "720"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "35"))
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
# Local-first contextual AI. Ollama runs on the user’s machine and needs no cloud API key.
OLLAMA_ENABLED = os.getenv("OLLAMA_ENABLED", "false").lower() in {"1", "true", "yes"}
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "nemotron-mini:4b")
OLLAMA_REQUEST_TIMEOUT = float(os.getenv("OLLAMA_REQUEST_TIMEOUT", "60"))
WORKSPACE_ID = os.getenv("WORKSPACE_ID", "ws-contexa-demo")
AI_VERIFICATION_ENABLED = os.getenv("AI_VERIFICATION_ENABLED", "false").lower() in {"1", "true", "yes"}
