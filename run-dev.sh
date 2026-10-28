#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
[ -f .env ] || cp .env.example .env
if [ ! -d frontend/node_modules ]; then (cd frontend && npm install); fi
(cd frontend && npm run dev) &
frontend_pid=$!
cleanup() { kill "$frontend_pid" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
