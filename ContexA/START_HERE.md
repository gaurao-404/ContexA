# Start ContexA

## Fastest path: local demo (Windows)

Requirements: Python 3.11+ (3.12 recommended), Node.js 20+ (22 recommended), and npm. Internet access is required on the first run to install Python/npm packages.

1. Extract the source archive to a writable folder.
2. Double-click `run-submission.bat`. It creates a Python virtual environment, installs backend dependencies, starts Vite, and starts FastAPI.
3. Open `http://localhost:5173`. API documentation is at `http://localhost:8000/docs`; health is at `http://localhost:8000/api/health`.
4. Sign in with the local demo account:

   - Email: `admin@contexa.local`
   - Password: `ContexA!2026`

5. On the dashboard, select **Prepare demo workspace** to create clearly labelled sample content and findings.

The demo uses deterministic rules only. It does not need Ollama, a cloud AI key, Cloudflare, Supabase, SMTP, or a public URL. Do not use seeded demo credentials for real content or internet-exposed deployments.

## Manual start

Backend (from the project root):

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt
$env:APP_ENV = 'demo'
$env:AUTH_MODE = 'local'
$env:OLLAMA_ENABLED = 'false'
$env:AI_VERIFICATION_ENABLED = 'false'
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Frontend (second terminal):

```powershell
cd frontend
npm install
$env:VITE_AUTH_MODE = 'local'
$env:VITE_SUBMISSION_MODE = 'true'
npm run dev
```

## Public demo

For a short-lived evaluation service, apply `render.demo.yaml` as a Render Blueprint. It uses demo accounts, disabled signup, rules-only checks, and a free Render Postgres database. Render Free Postgres is temporary and must not be used for confidential or business-critical data. Confirm the service and database are created in the intended Render workspace.

## Before real users

Do not just switch `APP_ENV=production`. Complete all requirements in [PRODUCT_READINESS.md](PRODUCT_READINESS.md) and [BACKEND_DEPLOYMENT_RUNBOOK.md](BACKEND_DEPLOYMENT_RUNBOOK.md): production Supabase access, migration/RLS verification, persistent PostgreSQL, a durable private object store, SMTP, malware scanning, monitoring, backups, and a security review.
