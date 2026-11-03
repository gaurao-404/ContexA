# ContexA — Staging and Production Runbook

This runbook covers the remaining environment-specific release checks. The code contains adapters and preflight scripts; live SMTP, PostgreSQL RLS, ClamAV and S3/R2 checks must be run with the deployment owner's own credentials and services. For Cloudflare Pages, the API Worker, Turnstile, private R2, AI Gateway and origin locking, follow [`CLOUDFLARE_HACKATHON_DEPLOYMENT.md`](CLOUDFLARE_HACKATHON_DEPLOYMENT.md).

## 1. Clean local backend regression

From the repository root:

```bash
python -m pip install -r backend/requirements.txt
cd backend
```

PowerShell:

```powershell
$env:APP_ENV = "test"
$env:DATABASE_URL = "sqlite:////tmp/contexa-round3-tests.db"
$env:OLLAMA_ENABLED = "false"
$env:AI_VERIFICATION_ENABLED = "false"
python -m pytest -q
```

macOS/Linux:

```bash
APP_ENV=test DATABASE_URL=sqlite:////tmp/contexa-round3-tests.db OLLAMA_ENABLED=false AI_VERIFICATION_ENABLED=false python -m pytest -q
```

Use a fresh temporary database for a reproducible run. Do not run the suite against a developer's existing `backend/contexa.db` because its demo users, rate-limit history and workspace data can affect authentication assertions.

## 2. Frontend production build

```bash
cd frontend
npm install --no-audit --no-fund
npm run build
```

Commit the generated `package-lock.json` after reviewing it. Once a lock file exists, switch local/CI release installs to `npm ci`. The included GitHub Actions workflow installs dependencies and runs `npm run build` on pushes and pull requests.

## 3. Choose the correct Render profile

### Temporary evaluator/demo profile

Use `render.demo.yaml` only for a short-lived demonstration. It disables public signup, email delivery, Ollama/cloud AI, malware scanning and external object storage. It uses Render Free services; the web service can sleep while idle, its local filesystem is ephemeral, and Free Postgres expires after 30 days. Do not upload confidential documents or treat this as a durable user service. See the [Render free plan limitations](https://render.com/docs/free).

### Public accounts / production-capable profile

Use `render.yaml`. This provisions paid-capable web/database resources and a private ClamAV service. It requires a payment method and provider secrets. Review resource plans, region, storage costs and expected usage before deploying; creating a Blueprint may incur charges.

Required Render environment values:

- `SECRET_KEY`: use the generated value from the Blueprint; do not replace it with a sample secret.
- `PUBLIC_APP_URL`: exact public HTTPS URL assigned to the web service.
- `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`: valid sender credentials.
- `SMTP_PORT=587`, `SMTP_USE_TLS=true`, `SMTP_USE_SSL=false` for STARTTLS; or use port 465 with `SMTP_USE_SSL=true` and `SMTP_USE_TLS=false` if the provider requires implicit TLS.
- `S3_BUCKET`, `S3_REGION`, `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`: private object bucket credentials. For Cloudflare R2, use region `auto` and endpoint `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`.
- Keep `EMAIL_VERIFICATION_REQUIRED=true`, `ENABLE_POSTGRES_RLS=true`, `REQUIRE_PRIVATE_OBJECT_STORAGE=true`, `REQUIRE_MALWARE_SCAN=true`, and `UPLOAD_SCAN_MODE=clamd` for public account onboarding.

Render Free web services cannot send outbound SMTP traffic on ports 25/465/587; Free Postgres expires 30 days after creation and has no backups. Use paid-capable resources for a durable public signup deployment. See [Render free plan limitations](https://render.com/docs/free) and [Render web services](https://render.com/docs/web-services).

## 4. Test email verification and password recovery delivery

Set the SMTP environment variables in the same environment as the app. From the repository root:

```bash
python ops/check_smtp.py
python ops/check_smtp.py --to your-test-address@example.com
```

The first command checks connection, authentication and TLS negotiation but sends no message. The second sends a real test message. The application supports STARTTLS and implicit TLS; it rejects plaintext SMTP in production. Never paste SMTP credentials into source control or issue logs.

## 5. Configure private S3-compatible storage

Create a private bucket and issue credentials scoped to only that bucket. For Cloudflare R2, the S3-compatible API uses region `auto`, endpoint `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`, and API credentials with Object Read & Write scoped to the selected bucket. See [Cloudflare R2 S3 setup](https://developers.cloudflare.com/r2/get-started/s3/).

Configure `S3_BUCKET`, `S3_REGION`, `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` and `S3_PREFIX`. Leave the bucket private; do not enable public object access. For AWS S3, prefer workload identity/IAM where available and enable bucket default encryption and versioning. For R2, use its provider-side encryption defaults and do not set an unsupported S3 encryption header.

Run the write/read/delete preflight:

```bash
python ops/check_object_storage.py
```

This writes a unique temporary object, reads it back, compares its bytes and deletes it. Run it only against a designated health-check prefix in the intended private bucket.

## 6. Verify ClamAV malware scanning

The production Blueprint provisions a private ClamAV service and configures the backend to fail closed when scanning is unavailable. Do not expose port 3310 publicly.

For local Docker Compose:

```bash
docker compose -f docker-compose.yml -f docker-compose.security.yml --profile security up --build
```

After the daemon is healthy, run:

```bash
python ops/check_clamd.py
```

The script sends `PING` and the harmless EICAR antivirus test signature via `INSTREAM`; a correct scanner identifies the test signature. Never use a real malware sample for this check. If the scanner is enabled but unreachable, ContexA rejects uploads with a service-unavailable response rather than skipping inspection.

## 7. Verify PostgreSQL Row-Level Security

Use the exact application database role for checks. It must not be a superuser or have `BYPASSRLS`. The production app startup enables and forces RLS on all workspace-owned tables and verifies policies. Apply/review `ops/round3_full_extension_postgres.sql` before staging cutover if your database was migrated manually.

Run the SQL checks:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f ops/verify_postgres_security.sql
```

Run the application-level cross-tenant sentinel test:

```bash
python ops/verify_postgres_rls.py
```

Expected: all 29 workspace-owned tables have RLS and FORCE RLS enabled, all 29 have the `contexa_workspace_isolation` policy, the application role is not superuser/BYPASSRLS, and a sentinel inserted under workspace A cannot be read under workspace B. Run this in staging before public data is introduced.

## 8. Backup and restore drills

Use the included `ops/backup_postgres.sh` and `ops/restore_postgres.sh` only after setting the correct database credentials and destination. Store backups outside the application service, encrypt them, restrict access, and test restores into a separate staging database. Configure object-store lifecycle/versioning or backup policy separately; a database backup alone does not preserve uploaded source files.

## 9. Remaining independent security/operations work

- Add MFA/OIDC SSO, refresh-token rotation and per-device session management.
- Enable and tune Cloudflare account-level WAF/bot controls. The bundled Worker includes approximate per-location auth/upload throttles and an optional shared-secret origin lock; preserve backend throttling. For strict global limits, use a coordinated backend limiter or Durable Objects.
- Move parsing to sandboxed background workers with CPU/memory/time limits and durable job queues.
- Add structured log aggregation, metrics, traces, alert routing and incident response.
- Perform scheduled encrypted database/object-store backups and documented restore drills.
- Anchor signed audit-chain checkpoints in an independently controlled immutable store.
- Run a blind, human-labelled evaluation set of 50–100 real documents; report category-level precision/recall, false positives, citation validity and reviewer time saved.
- Perform dependency, secrets and independent penetration testing before handling confidential customer content.
