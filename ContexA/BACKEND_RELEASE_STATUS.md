# ContexA backend release status

**Scope:** backend, database, security, storage, integrations, deployment configuration and operations. Frontend source and UI changes are intentionally excluded.

## Verified in this workspace

- Backend application, Trust OS capability modules, schema/migration runner, Supabase JWT/JWKS verification, roles and workspace scoping.
- Supabase email-verification claim hook, project-specific Auth configuration templates, and a read-only live-session reader role/view with a connection smoke-check script.
- Immediate session revocation: the backend logout endpoint revokes the current Supabase Auth session using the provider Auth API; subsequent API calls check `(session_id, sub)` against a private, read-only projection of the issuing project's `auth.sessions` table. A missing session returns `401`; an unavailable session database returns `503` (fail closed).
- Production CORS now requires exact HTTPS origins; localhost, HTTP, wildcard-like, path, query and fragment origins are rejected.
- Forced RLS creation and metadata verification for the workspace-owned tables listed in `backend/app/database.py`.
- Backend regression suite: **91 tests pass when run per test file with a fresh temporary SQLite database**. Running the entire suite in one process remains unreliable in this workspace and intermittently stalls near the final tests; isolated file runs have all passed.
- Cloudflare Worker syntax and tests: **6 passed**.
- Cloudflare GitHub Actions workflows now validate required deployment values, upload Worker secrets alongside code, and pass Supabase/Turnstile public build variables to Pages. The Wrangler config requires the two Worker runtime secrets.
- Python compilation and static configuration checks: passed.
- Clean source packaging: runtime databases, uploaded files, `.env` overrides, bytecode and test caches are excluded.

## Production database topology

The production deployment is configured to use the target Supabase project's PostgreSQL database for application data (`DATABASE_URL` via the `contexa_app` role) and Auth-session liveness checks (`SUPABASE_SESSION_DATABASE_URL` via the read-only `contexa_session_reader` role). The Render production Blueprint therefore does not provision a separate Render PostgreSQL database. The temporary demo profile remains self-contained and uses its own short-lived Render database. This topology is prepared in source only; it has not been applied to the inaccessible hosted project.

## Local build/test evidence

Run from the extracted repository root:

```bash
cd backend
python -m pytest -q
cd ../cloudflare/worker
node --check src/index.js
npm test
```

The test counts above are local results. They are not evidence that live cloud services are provisioned or deployed.

## Not yet verified against live infrastructure

| Workstream | State | Reason |
|---|---|---|
| Push source to `gaurao-404/ContexA` | Blocked | GitHub create-branch API returned `403 Resource not accessible by integration`. The connected GitHub OAuth profile is `gaurao-404`, while the active GitHub App installation is on `Aniket-Barde`. |
| Pull request / GitHub Actions | Blocked | No feature branch exists, so there is no PR or CI run for this release. |
| Intended Supabase project `amxhfdbsvlzhyogwnxaw` | Blocked | It is not in the connected account's project list and project access returned permission denied. The only visible project is `uxakhyzpaoujplxxjbih`, currently inactive; it was not modified because it is not the configured target. |
| Supabase migrations, Auth hook and session reader | Not applied | Requires authorized access to the intended Supabase project and administrator SQL access. |
| RLS isolation staging test | Not run | Requires a reachable PostgreSQL staging database and the production application role. |
| SMTP delivery | Not run | SMTP host and credentials are not configured in the current runtime. |
| Private object storage | Not run | Bucket and provider credentials are not configured. |
| ClamAV deployment | Not run | No scanner service is running/reachable in this workspace. |
| AWS KMS and S3 Object Lock | Not deployed | AWS account credentials/role and target bucket/key are unavailable. |
| Cloudflare Worker/Pages deployment | Not deployed | User reports completing Cloudflare deployment-token and private R2 bucket setup, but no direct Cloudflare account connector is available here. Deployment is staged through GitHub Actions; the GitHub branch-write API still returns 403, so the workflow cannot yet be pushed or run. |
| Backup/restore drill | Not run | No staging PostgreSQL instance is accessible. |
| Terraform validation | Not run | Terraform CLI is not installed in this runtime. |

## Required account-side actions

1. Authorize the GitHub App for the **`gaurao-404`** account with Contents read/write and Pull requests read/write permissions. The current installation is attached to `Aniket-Barde` and cannot create a branch in `gaurao-404/ContexA`. A retry after the reported Cloudflare setup still returned HTTP 403, so the source was not pushed and no workflow was run.
2. Connect the Supabase organization/project that owns `amxhfdbsvlzhyogwnxaw`, or grant the connected identity project access. Do not substitute `uxakhyzpaoujplxxjbih` without confirming that it is the intended project.
3. After Supabase access is restored, apply `infra/supabase/custom_access_token_hook.sql`, `infra/supabase/contexa_app_role.sql`, and `infra/supabase/contexa_session_reader.sql` in the documented order. Set the session-reader password out-of-band and configure `SUPABASE_SESSION_DATABASE_URL` in the backend host secret store.
4. Configure hosting secrets/variables for SMTP, S3/R2, ClamAV, Cloudflare and AWS. For Cloudflare GitHub Actions, use the required repository secrets and variables documented in `CLOUDFLARE_HACKATHON_DEPLOYMENT.md`. Then run the `ops/` validators and the PostgreSQL RLS sentinel test against staging.

## Production caution

Do not set a service-role key, database password, SMTP password, AWS credentials, Cloudflare secret, or Supabase session-reader URL in any `VITE_*` variable or commit them to the repository. Production Supabase mode defaults to requiring live session validation and refuses startup without `SUPABASE_SESSION_DATABASE_URL`.
