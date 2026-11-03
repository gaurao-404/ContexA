# ContexA Studio — Cloudflare deployment playbook

This release uses Cloudflare as the public edge and storage layer while keeping the FastAPI application on a Python-capable host. **Cloudflare Pages does not run this FastAPI backend.** The supported split is:

```text
Browser
  ├─ Cloudflare Pages (Vite / React static app)
  └─ Cloudflare Worker (same-origin-style API edge)
        └─ FastAPI origin (Render / Fly.io / Railway / container host)
              ├─ Managed PostgreSQL + verified workspace RLS
              ├─ Private Cloudflare R2 bucket (S3 API)
              ├─ SMTP provider (account verification / recovery)
              └─ Optional Cloudflare AI Gateway → Claude API

Cloudflare Turnstile → browser challenge → FastAPI Siteverify on login/signup
```

The Worker is intentionally a narrow `/api/*` reverse proxy; it is not an open proxy. It adds request IDs and security/CORS headers and applies edge rate limits to authentication and upload endpoints. The application database's own throttles remain enabled as the authoritative fallback. Cloudflare's simple rate-limit bindings are approximate and scoped per Cloudflare location/colo; do not treat them as a global exact quota or a replacement for backend controls.

## 0. Choose hostnames

Use these examples consistently (replace them with your real domains):

- Frontend: `https://app.example.com` (Cloudflare Pages custom domain; `*.pages.dev` also works)
- API Worker: `https://api.example.com` (recommended) or the Worker `*.workers.dev` hostname
- FastAPI origin: the private/public origin URL supplied by Render/Fly/Railway; only the Worker should be used by the browser

The API origin must be reachable by the Worker over HTTPS. It is a server-side Worker variable (not a browser variable); never put it in frontend code.

## 1. Deploy FastAPI first

1. Push the extracted project to a private GitHub repository. Do not commit `.env`, credentials, database dumps or customer documents.
2. Create the backend service using the existing `render.yaml`/`DEPLOY_PUBLIC_LINK.md`, or deploy `backend/Dockerfile` to another Python container host.
3. Provision managed PostgreSQL. Use a dedicated non-superuser application DB role without `BYPASSRLS`; run the existing migration and RLS verification procedure in `DEPLOY_PUBLIC_LINK.md` and `ops/` against the real role.
4. Configure at minimum:

   | Variable | Production value |
   |---|---|
   | `APP_ENV` | `production` |
   | `SECRET_KEY` | Long random secret from the host's secret manager |
   | `DATABASE_URL` | Managed PostgreSQL URL using the installed psycopg v3 driver |
   | `ENABLE_POSTGRES_RLS` | `true` |
   | `ALLOW_SIGNUP` | `true` only if public self-registration is intended |
   | `EMAIL_VERIFICATION_REQUIRED` | `true` for public accounts |
   | `PUBLIC_APP_URL` | `https://app.example.com` |
   | `ALLOWED_ORIGINS` | Exact frontend origin(s), comma-separated; no trailing slash |
   | `CLOUDFLARE_EDGE_ENABLED` | `true` after the Worker is deployed |
   | `PUBLIC_API_URL` | `https://api.example.com` |

5. Configure SMTP before enabling public verification. Run `python ops/check_smtp.py` from a correctly configured environment. Never set `EMAIL_VERIFICATION_REQUIRED=true` without working SMTP.
6. Wait for `https://YOUR-ORIGIN/api/health` to return `{"status":"ok"}`. This is the origin check; the browser should later use the Worker URL instead.

## 2. Deploy the Cloudflare Worker API edge

The Worker is in `cloudflare/worker/` and is deployed separately from Pages.

1. Create a Cloudflare account and install Node.js 22+ locally.
2. In a terminal:

   ```bash
   cd cloudflare/worker
   npm install
   npx wrangler login
   ```

3. Update `wrangler.jsonc` → `vars.ALLOWED_ORIGINS` with the exact Pages/custom frontend origins. Keep the `AUTH_LIMITER` and `UPLOAD_LIMITER` bindings. If you create multiple Workers in the same account, choose namespace IDs that are unique for your account.
4. Configure the Worker origin and secrets. The HTTPS FastAPI origin is supplied as Worker variable `API_ORIGIN`; the secret values are uploaded separately. For a manual Wrangler deployment:

   ```bash
   npx wrangler deploy --var "API_ORIGIN:https://contexa-api.onrender.com" --var "ALLOWED_ORIGINS:https://contexa-studio.pages.dev"
   npx wrangler secret put ORIGIN_SHARED_SECRET
   npx wrangler secret put TRUTH_DRIFT_CRON_TOKEN
   ```

   Set the exact same `ORIGIN_SHARED_SECRET` value as backend `CLOUDFLARE_ORIGIN_SHARED_SECRET`, and the exact same `TRUTH_DRIFT_CRON_TOKEN` as backend `TRUTH_DRIFT_CRON_TOKEN`. After the Worker is deployed and successfully forwarding API traffic, set `CLOUDFLARE_EDGE_ENABLED=true` on FastAPI. When this flag and the shared secret are both configured, the backend rejects direct `/api/*` calls that bypass the Worker. If you intentionally leave the shared secret blank, the Worker still fronts the API but the origin itself remains directly reachable; the Settings panel distinguishes this as an unconfigured origin lock.

5. Deploy and tail logs:

   ```bash
   npx wrangler deploy
   npx wrangler tail
   ```

6. Check `https://YOUR-WORKER.workers.dev/edge-health`. Expect `status: ok` and `origin_configured: true`. Then check `https://YOUR-WORKER.workers.dev/api/health`.
7. For a custom API hostname, attach `api.example.com` to this Worker in Cloudflare's Workers & Pages → Settings → Domains & Routes. Keep the public browser base URL and the `PUBLIC_API_URL` value in sync.

The Worker only forwards `/api/*`; other paths intentionally return 404. Keep the origin reachable by the Worker and do not expose database, object-store or internal service ports publicly.

**GitHub Actions Worker deployment:** add repository secrets `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `ORIGIN_SHARED_SECRET`, and `TRUTH_DRIFT_CRON_TOKEN`. Add repository variables `ENABLE_CLOUDFLARE_WORKER_DEPLOY=true`, `API_ORIGIN` (HTTPS FastAPI origin), and `ALLOWED_ORIGINS` (comma-separated exact production frontend origins; no localhost). The Worker workflow uploads its two runtime secrets alongside the code and injects the origin/CORS values as Worker variables. Without the enable variable, the deployment job remains skipped. Keep the shared origin secret identical to backend `CLOUDFLARE_ORIGIN_SHARED_SECRET`, and the cron token identical to backend `TRUTH_DRIFT_CRON_TOKEN`.

**GitHub Actions Pages deployment:** add repository secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`. Add repository variables `ENABLE_CLOUDFLARE_PAGES_DEPLOY=true`, `CLOUDFLARE_PAGES_PROJECT=contexa-studio`, `VITE_API_URL` (the Worker HTTPS URL), `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`, and optional `VITE_TURNSTILE_SITE_KEY`. The publishable Supabase key and Turnstile site key are public build-time values. Do not put a Supabase secret/service-role key or Turnstile secret in a `VITE_*` variable.

## 3. Deploy the React frontend on Cloudflare Pages

Create a Pages project and connect the Git repository. Configure:

| Setting | Value |
|---|---|
| Framework preset | Vite |
| Root directory | `frontend` |
| Build command | `npm run build` |
| Build output directory | `dist` |
| Node version | `22` |

Set these Pages build environment variables:

- `VITE_API_URL=https://<worker-subdomain>.workers.dev` (or the custom Worker URL)
- `VITE_AUTH_MODE=supabase`
- `VITE_SUPABASE_URL=https://<project-ref>.supabase.co`
- `VITE_SUPABASE_PUBLISHABLE_KEY=<sb_publishable_...>` (public key only; never a secret/service-role key)
- `VITE_SUBMISSION_MODE=false` for the public deployment; use `true` only for the isolated hackathon demo with seeded demo accounts
- `VITE_TURNSTILE_SITE_KEY=<site key>` after configuring Turnstile; leave unset only if the backend Turnstile secret is also unset

The `frontend/public/_redirects` and `_headers` files provide SPA fallback and a baseline browser security policy. If your API hostname is not `api.example.com` or `*.workers.dev`, add it to the `connect-src` directive in `frontend/public/_headers`. Update the same origin in the Worker `ALLOWED_ORIGINS` and backend `ALLOWED_ORIGINS` settings. Rebuild Pages after changing Vite variables; they are embedded at build time.

## 4. Configure Cloudflare Turnstile (optional but recommended for public signup)

1. In Cloudflare dashboard, create a Turnstile widget and allow the exact frontend hostnames (`app.example.com` and/or the Pages hostname used for the demo).
2. Set the **site key** in Pages as `VITE_TURNSTILE_SITE_KEY`.
3. Set the **secret key** on the FastAPI host as `TURNSTILE_SECRET_KEY` and set `TURNSTILE_EXPECTED_HOSTNAME` to the exact frontend hostname (without protocol).
4. Redeploy/rebuild both pieces and test login and signup.

Set both keys together. When the backend secret is present, the backend validates the token with Cloudflare Siteverify, checks the expected hostname (when configured) and verifies the `auth` action. Tokens are short-lived and single-use; the client gets a fresh token after each auth attempt. The local demo remains frictionless when both keys are blank. Do not rely on a client-side widget alone: server-side Siteverify is mandatory.

## 5. Configure private Cloudflare R2 uploads (optional)

1. Create an R2 bucket such as `contexa-private`. Keep it private; do not enable public bucket access for user uploads.
2. Create a scoped R2 API token with only the bucket permissions needed by the application. Copy the access key ID and secret once.
3. Configure these backend secrets/environment variables:

   ```dotenv
   S3_BUCKET=contexa-private
   S3_REGION=auto
   S3_ENDPOINT_URL=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
   S3_ACCESS_KEY_ID=<R2_ACCESS_KEY_ID>
   S3_SECRET_ACCESS_KEY=<R2_SECRET_ACCESS_KEY>
   S3_PREFIX=contexa
   S3_FORCE_PATH_STYLE=false
   S3_SERVER_SIDE_ENCRYPTION=
   REQUIRE_PRIVATE_OBJECT_STORAGE=true
   ```

4. Run `python ops/check_object_storage.py` from the deployed backend environment with the same credentials. Test upload, download and delete with synthetic files. Configure bucket lifecycle rules, backups/retention and least-privilege credentials.

R2 uses the S3-compatible API, the account-specific endpoint and region `auto`. Leave `S3_SERVER_SIDE_ENCRYPTION` blank for R2-managed encryption; do not assume AWS-specific SSE headers are supported.

## 6. Optional Cloudflare AI Gateway

AI remains optional. Deterministic rules and offline embeddings work without an external model. To proxy Claude through an AI Gateway, create a gateway in Cloudflare and configure the FastAPI service:

```dotenv
ANTHROPIC_API_KEY=<provider-key-or-your-approved-key-source>
ANTHROPIC_MODEL=claude-sonnet-4-6
ANTHROPIC_BASE_URL=https://gateway.ai.cloudflare.com/v1/<ACCOUNT_ID>/<GATEWAY_ID>/anthropic
# Optional, only if your gateway is configured to require Cloudflare gateway auth:
CLOUDFLARE_AI_GATEWAY_TOKEN=<gateway-token>
```

The base URL is server-side only. Keep provider/gateway keys out of Pages variables. Validate that the chosen gateway's provider route and authentication mode match your Cloudflare account configuration. The app reports this as an optional integration, not as a requirement for governance checks.

## 6A. Trust OS scheduled monitoring and signed passports

The Worker configuration includes a six-hour Cron trigger (`0 */6 * * *`) for scheduled Truth Drift scans. Configure three separate Worker secrets in `cloudflare/worker/`:

```bash
npx wrangler deploy --var "API_ORIGIN:https://contexa-api.onrender.com" --var "ALLOWED_ORIGINS:https://contexa-studio.pages.dev"
npx wrangler secret put ORIGIN_SHARED_SECRET
npx wrangler secret put TRUTH_DRIFT_CRON_TOKEN
```

Set the same `ORIGIN_SHARED_SECRET` as backend `CLOUDFLARE_ORIGIN_SHARED_SECRET`, and the same `TRUTH_DRIFT_CRON_TOKEN` as backend `TRUTH_DRIFT_CRON_TOKEN`. Keep them distinct and do not commit them. Set backend `TRUST_PASSPORT_SIGNING_KEY` to a stable random secret of at least 32 characters and `PUBLIC_APP_URL` to the HTTPS Pages/custom frontend URL. Passport signatures depend on the stable key; rotating it requires a planned keyring migration, not a casual secret rotation.

The scheduled Worker calls `POST /api/internal/truth-drift/scan-due`; it does not scan every possible public URL. A workspace administrator must register sources in ContexA, and the scanner only handles supported public HTTPS sources within its size/type/SSRF restrictions. QR verification uses the public signed-attestation index and `/verify/<id>` SPA route; it does not make the underlying R2 document public. See [TRUST_OS_PRODUCTION_GUIDE.md](TRUST_OS_PRODUCTION_GUIDE.md) for migration, module boundaries, limitations and production acceptance tests.

## 7. Cloudflare dashboard security checklist

- Keep R2 private and use bucket-scoped access credentials.
- Keep Worker `ORIGIN_SHARED_SECRET` and `TRUTH_DRIFT_CRON_TOKEN`, the backend Turnstile secret and AI Gateway token in managed secrets. `API_ORIGIN` is a server-side Worker variable. Never put secrets in `wrangler.jsonc`, Pages variables or Git.
- Enable available Cloudflare managed WAF rules and bot controls for the frontend/API hostnames; tune exceptions only after checking application logs. Plan availability differs by account.
- Keep the Worker route restricted to the API hostname. The bundled Worker has a narrow path allowlist and CORS origin allowlist.
- Preserve backend login/signup/upload throttles. Worker simple rate-limit bindings provide an extra approximate edge layer, not a global account-wide hard quota.
- Configure TLS end-to-end, a database backup schedule, R2 lifecycle/retention, alerting and origin access restrictions.
- Do not expose ClamAV on the public internet. Enable `UPLOAD_SCAN_MODE=clamd` and `REQUIRE_MALWARE_SCAN=true` only after a private scanner is deployed and tested using `ops/check_clamd.py`.

## 8. Release smoke test

After Pages, Worker and backend are deployed:

1. Open `/edge-health` on the Worker and `/api/health` through the Worker.
2. Register a throwaway account; verify email; log out; sign in again. With Turnstile enabled, complete the challenge twice to prove a fresh single-use token is obtained.
3. Create Workspace A, invite a member, then create Workspace B separately. Confirm cross-workspace reads/writes fail and run `ops/verify_postgres_rls.py` / the SQL verification as the application DB role.
4. Upload a synthetic PDF and confirm the document can be retrieved from private R2; check storage with `ops/check_object_storage.py`.
5. Review a purposely unsupported claim, attach evidence, approve/reject it, simulate a policy change, run a benchmark, and verify the audit chain.
6. Check Cloudflare Pages function-free SPA fallback, Worker logs, backend logs, SMTP delivery and restore procedures.

## 9. What is and is not done in this ZIP

**Implemented in source:** Worker API gateway, exact-origin CORS policy, request IDs/security headers, optional edge throttling, optional shared-secret origin lock, Pages SPA/security headers, frontend Turnstile widget, backend server-side Turnstile validation, Cloudflare R2 S3-compatible configuration, optional AI Gateway Anthropic proxy, settings readiness indicators, and automated backend/Worker security tests.

**Still requires your account/credentials and a live deployment:** creating the Pages project, Worker deployment/custom domain, backend hosting, DNS, R2 bucket and scoped keys, Turnstile keys, SMTP credentials, managed PostgreSQL/RLS verification, optional AI Gateway credentials, and end-to-end tests. The source code cannot create these resources without your Cloudflare/hosting account and secrets. Do not describe these integrations as live until the smoke tests above pass.


## Enterprise foundation deployment notes

- The Cloudflare Pages frontend uses `VITE_AUTH_MODE`, `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` build-time values. Set `VITE_AUTH_MODE=supabase` for the intended hosted deployment; only a publishable key belongs in the frontend.
- `.github/workflows/cloudflare-pages.yml` deploys the frontend when repository variable `ENABLE_CLOUDFLARE_PAGES_DEPLOY=true` is set. Configure repository variables `CLOUDFLARE_PAGES_PROJECT=contexa-studio`, `VITE_API_URL` (the Worker HTTPS URL), `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`, and optional `VITE_TURNSTILE_SITE_KEY`, plus repository secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`. The publishable Supabase key and Turnstile site key are public build-time values; never add a Supabase secret/service-role key or Turnstile secret to a `VITE_*` variable.
- AWS KMS/S3 provisioning is documented in `infra/aws/README.md`. The Terraform module attaches permissions to an existing ECS task role. For AWS-backed production, run the FastAPI API on ECS/Fargate with that task role; the existing Render blueprint remains a non-AWS-origin option and does not provision an AWS workload identity.
- Supabase issuer/JWKS and workspace-linking requirements are documented in `infra/supabase/README.md`.
