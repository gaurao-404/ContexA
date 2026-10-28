#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Submission mode is fully rules-only; no Ollama service, cloud endpoint or API key.
export APP_ENV=demo
export OLLAMA_ENABLED=false
export AI_VERIFICATION_ENABLED=false
unset ANTHROPIC_API_KEY || true
export VITE_SUBMISSION_MODE=true

if [ ! -d .venv ]; then python3 -m venv .venv; fi
source .venv/bin/activate
if [ ! -f .venv/.contexa-backend-ready ]; then
  python -m pip install --upgrade pip
  python -m pip install -r backend/requirements.txt
  touch .venv/.contexa-backend-ready
fi
[ -f .env ] || cp .env.example .env
if [ ! -d frontend/node_modules ]; then (cd frontend && npm install); fi
(cd frontend && npm run dev) &
frontend_pid=$!
cleanup() { kill "$frontend_pid" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
printf '\nContexA Submission Mode — no Ollama or API key required\n'
printf 'Frontend: http://localhost:5173\nAPI docs:  http://localhost:8000/docs\n'
printf 'Demo login: admin@contexa.local / ContexA!2026\n\n'
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
