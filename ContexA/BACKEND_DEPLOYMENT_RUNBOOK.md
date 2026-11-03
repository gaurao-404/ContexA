# ContexA backend deployment and acceptance runbook

Frontend changes are out of scope. Keep the existing frontend directory untouched while completing these steps.

## 1. GitHub source sync

Target repository: `https://github.com/gaurao-404/ContexA`

Create a feature branch named `backend/platform-completion` from `main`, overlay the backend release files, inspect the diff, run GitHub Actions, and open a PR. Do not push directly to `main`.

The current GitHub integration returned `403 Resource not accessible by integration`. Re-authorize the GitHub App on the `gaurao-404` account with Contents read/write and Pull requests read/write permissions before attempting the branch push again.

## 2. Supabase project configuration

Target project reference: `amxhfdbsvlzhyogwnxaw`.

Verify the target is active and accessible before applying SQL. Do not apply these scripts to another project based only on account ownership or a similar project name.

Apply in this order as a project/database administrator:

1. `infra/supabase/custom_access_token_hook.sql` — enables the authoritative `email_verified` claim derived from `auth.users.email_confirmed_at`.
2. `infra/supabase/contexa_app_role.sql` — creates/configures the non-superuser ContexA application DB role and grants it only the application-schema ownership/permissions required for migrations and app RLS policies.
3. `infra/supabase/contexa_session_reader.sql` — creates a read-only, non-login role and a private view exposing only session ID and user ID. Then set a high-entropy password out-of-band:

```sql
ALTER ROLE contexa_session_reader WITH LOGIN PASSWORD '<strong random password>';
```

Configure the backend host with two distinct server-side connection URIs: the normal application connection for `contexa_app`, and the read-only session lookup connection for `contexa_session_reader`. Use the Supabase Dashboard's Transaction Pooler URI (port/host as actually shown by the dashboard); do not guess the pooler hostname or embed either password in source control.

```text
DATABASE_URL=<Supabase Transaction Pooler URI for contexa_app>
SUPABASE_SESSION_DATABASE_URL=<Supabase Transaction Pooler URI for contexa_session_reader>
SUPABASE_SESSION_CHECK_REQUIRED=true
SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
```

Verify the least-privilege reader before deploying:

```bash
python ops/check_supabase_session_reader.py
```

Use the same Supabase project for `SUPABASE_URL`, `SUPABASE_JWT_ISSUER`, `SUPABASE_JWKS_URL` and the session database URI. Use asymmetric ES256 or RS256 signing keys. Never publish the session database URI or any service-role/secret key.

Set the custom access-token hook in Supabase Authentication → Hooks. Verify confirmed users receive `email_verified: true` and unconfirmed users receive `false` before switching production traffic.

## 3. Database and tenant isolation

Use a non-superuser, `NOBYPASSRLS` application role. Ensure `ENABLE_POSTGRES_RLS=true`. After deployment:

```bash
cd backend
python -m pytest -q
cd ..
python ops/verify_postgres_rls.py
```

Also run the read-only checks in `ops/verify_postgres_security.sql`. The sentinel script inserts temporary rows in two random workspaces and verifies each workspace can see only its own row before deleting them.

Do not run the sentinel check with the `postgres` superuser or any `BYPASSRLS` role. It must use the actual application connection string.

## 4. External services

Configure secrets only in the hosting provider's secret manager:

- Backend: `SECRET_KEY`, `DATABASE_URL` (Supabase `contexa_app` URI), Supabase project settings, `SUPABASE_SESSION_DATABASE_URL` (Supabase `contexa_session_reader` URI), `SUPABASE_PUBLISHABLE_KEY`, `PUBLIC_APP_URL`, `ALLOWED_ORIGINS`.
- Email: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, `SMTP_USE_TLS=true` or `SMTP_USE_SSL=true` (not both).
- Private uploads: S3/R2 endpoint, bucket, region, and access values or a workload identity. Keep `REQUIRE_PRIVATE_OBJECT_STORAGE=true` in production.
- Malware scanning: `UPLOAD_SCAN_MODE=clamd`, `REQUIRE_MALWARE_SCAN=true`, and a private reachable ClamAV daemon.
- Cloudflare: Worker secrets including the origin shared secret and Truth Drift cron token; configure Pages variables using only the publishable browser key.
- AWS: use a workload IAM role for KMS signing and S3 Object Lock. Avoid long-lived AWS credentials in application environment files.

Run the corresponding non-destructive checks:

```bash
python ops/check_smtp.py
python ops/check_object_storage.py
python ops/check_clamd.py
python ops/verify_passport_signature.py
```

To test actual email delivery, pass `--to` to `check_smtp.py` with an approved test mailbox. The storage test writes, reads and deletes one temporary object. ClamAV check must report a live daemon. KMS/AWS validation must be run with the provisioned workload identity and retention policy.

## 5. Backup/restore

Only run against a disposable staging database first:

```bash
DATABASE_URL='<staging-db-uri>' bash ops/backup_postgres.sh
DATABASE_URL='<disposable-restore-db-uri>' bash ops/restore_postgres.sh <backup-file>
```

Verify row counts, constraints, RLS, application health and a sample passport verification after restore. Do not use production as the restore target.

## 6. Final backend acceptance gates

- GitHub branch contains the intended backend source diff; PR CI is green.
- Supabase issuer, JWKS, email verification hook and live session revocation all pass against the target project.
- Workspace RLS metadata and two-tenant sentinel test pass using the real application role.
- SMTP can send a test email; private storage round-trips; ClamAV is reachable and required for uploads.
- Cloudflare Worker/Pages are deployed and health checks pass; origin rejects direct API requests when edge lock is enabled.
- AWS KMS signature verifies from the public key; Object Lock retention/read-back is confirmed.
- Staging backup restores successfully and RLS re-verifies afterward.
- No unresolved critical security finding remains.

Only after these gates pass should backend API/schema contracts be frozen. Frontend and UI work remains deferred until the user explicitly asks to begin it.
