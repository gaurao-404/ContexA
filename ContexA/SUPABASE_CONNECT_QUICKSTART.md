# Connect your existing Supabase project to ContexA

This is the clean activation path for the Enterprise Trust OS release. The supplied project URL and publishable key are already wired into `frontend/.env.development` and `frontend/.env.production`. Supabase owns authentication. ContexA remains the source of truth for workspace membership, roles, governance records and audit history. The publishable key is public browser configuration; the API never treats it as a secret.

## 1. Supabase Dashboard

1. Open **Project Settings → API** and copy the **Project URL** and **Publishable key**. A legacy browser-safe `anon` key is also supported.
2. Open **Authentication → URL Configuration** and add `http://localhost:5173` plus the final deployed frontend URL to the allowed site/redirect URLs.
3. Enable the Email provider and require email confirmation. Configure custom SMTP before inviting real users.
4. Open **Authentication → Signing Keys** and activate an asymmetric **ES256** or **RS256** signing key. ContexA verifies JWT signatures through the JWKS endpoint; it does not accept legacy HS256-only verification in this configuration.
5. In **SQL Editor**, run `infra/supabase/custom_access_token_hook.sql`.
6. Open **Authentication → Hooks → Custom Access Token**, enable `public.contexa_custom_access_token_hook`, then check a confirmed and an unconfirmed user's issued JWT. The `email_verified` claim must be true only for a confirmed email.

## 2. Prepare the Supabase PostgreSQL runtime role

If you want Supabase Postgres to be ContexA's primary database, run `infra/supabase/contexa_app_role.sql` in the Supabase SQL Editor as the project database administrator. Replace the password placeholder with a unique random password of at least 32 characters before executing; the script refuses to create the role if the placeholder remains unchanged. If `contexa_app` already exists, rotate its password separately with `ALTER ROLE contexa_app PASSWORD '<new-random-password>';` and store it only in the backend host. This creates `contexa_app` with `NOSUPERUSER` and `NOBYPASSRLS`, transfers the existing public application tables to that role, and leaves forced tenant RLS enforceable. Do not use the built-in `postgres` role for the production API: it can bypass RLS and ContexA intentionally rejects that configuration.

Use the Supabase **Transaction Pooler** connection string for a long-running API when direct database connectivity is unavailable, require TLS (`sslmode=require`), and put the role password only in the backend host's `DATABASE_URL` secret. Do not share the database password in chat or commit it. ContexA applies additive schema migrations at startup, so the runtime role must own the application tables and have `CREATE` on the `public` schema.

The included production Render blueprint uses Supabase Postgres as the primary application database. A custom deployment can use a separately managed PostgreSQL database only if its operator intentionally chooses that architecture and separately provides the Supabase Auth-session reader connection.

## 3. Backend environment

Set these values in the backend host's private environment settings (Render, ECS, etc.):

```dotenv
AUTH_MODE=supabase
SUPABASE_URL=https://amxhfdbsvlzhyogwnxaw.supabase.co
SUPABASE_JWT_ISSUER=https://amxhfdbsvlzhyogwnxaw.supabase.co/auth/v1
SUPABASE_JWKS_URL=https://amxhfdbsvlzhyogwnxaw.supabase.co/auth/v1/.well-known/jwks.json
SUPABASE_JWT_AUDIENCE=authenticated
SUPABASE_JWT_ALGORITHMS=ES256,RS256
SUPABASE_REQUIRE_AAL2=false
```

The supplied root `.env.example` is set to `AUTH_MODE=supabase`, which disables ContexA local-password login and accepts only verified Supabase JWTs. Use `AUTH_MODE=hybrid` only in a deliberately separate migration/development environment where local-password fallback is required.

Also set `ALLOWED_ORIGINS` to the exact frontend origin(s), `PUBLIC_APP_URL` to the deployed frontend URL, and `DATABASE_URL` to the Supabase Postgres Transaction Pooler connection string for `contexa_app`. The production Render blueprint expects this external URI as a secret and does not create a second Render-managed database. This keeps ContexA workspace, governance, evidence and audit records in the same Supabase project as Auth while preserving the API-only data access boundary. Never use the built-in `postgres` or `service_role` credential for the application connection, and never expose database credentials in the frontend.

## 4. Frontend environment

The repository already contains `frontend/.env.development` for local Vite development and `frontend/.env.production` for the production Supabase provider. Both include the supplied public project URL and publishable key. The development profile points at `http://localhost:8000`; the production build obtains `VITE_API_URL` from the deployment environment. Do not overwrite these with the blank example. For custom builds, use:

```dotenv
VITE_AUTH_MODE=supabase
VITE_SUPABASE_URL=https://amxhfdbsvlzhyogwnxaw.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_IXCe0kqC14HJcCVV4GvmMw_DCx9XTeY
VITE_API_URL=https://YOUR_PUBLIC_CLOUDFLARE_WORKER_API_URL
VITE_SUBMISSION_MODE=false
```

The publishable key (or old `anon` key) is intended for browser use. Never use a `service_role`, `sb_secret_...`, database password or JWT signing secret as a `VITE_*` value. Rebuild/redeploy the frontend after changing any `VITE_*` values; Vite embeds them at build time.

## 5. Provision the first ContexA administrator

Create or invite the administrator in **Supabase → Authentication → Users** and ensure the email is confirmed. Then, from a shell attached to the backend deployment, run:

```bash
cd backend
python bootstrap_supabase_admin.py \
  --email admin@yourcompany.com \
  --name "Workspace Admin" \
  --workspace-name "Your Brand Team" \
  --confirm-email-verified
```

This creates a private ContexA workspace, a `Brand Admin` record, the starter rule set and an audit event. It does not call Supabase Admin APIs and does not need a service-role key. Existing matching ContexA users are not duplicated; they are linked on their first successful verified Supabase sign-in.

Additional team members must first exist as confirmed users in Supabase Auth, then be provisioned into the existing ContexA workspace:

```bash
cd backend
python bootstrap_supabase_admin.py \
  --email reviewer@yourcompany.com \
  --name "Legal Reviewer" \
  --workspace-id ws-PRINTED-WHEN-ADMIN-WAS-CREATED \
  --role "SME / Legal" \
  --confirm-email-verified
```

Available roles: `Brand Admin`, `Manager`, `SME / Legal`, `Creator`. The command rejects duplicate emails and unknown workspace IDs. Use the same workspace ID for members of one organization.

## 6. Verify in ContexA

1. Sign in through the single **Sign in securely** action.
2. Open **Trust Foundation** and select **Refresh**.
3. Confirm Identity displays `supabase` and `Configured`.
4. Verify an unprovisioned Auth user is denied, a wrong-project JWT is rejected, and cross-workspace access remains blocked.
5. Test sign-out and refresh-token rotation. Keep `SUPABASE_REQUIRE_AAL2=false` until the app's full TOTP challenge/enrollment flow has been configured and tested; enabling it early can lock users out.

## 7. Credentials that must stay private

Never paste or commit the Supabase `service_role` / secret API key, database password, JWT signing secret, SMTP password, AWS key or private signing key. The Project URL and Publishable key are public client configuration; they can be supplied through the Supabase connection or normal frontend build settings.


## Project-specific activation status

- The supplied project reference and publishable key are prefilled in the frontend development and production Vite env files. Supabase-only sign-in is enabled, and password recovery uses Supabase Auth with a neutral response to reduce account enumeration.
- The backend `.env.example` is prefilled with the matching issuer and JWKS URL. Copy it to `.env`, then replace `SECRET_KEY`, `TRUST_PASSPORT_SIGNING_KEY` and `TRUTH_DRIFT_CRON_TOKEN` with fresh random secrets before running the API.
- `VITE_API_URL` is intentionally not guessed. For local development it is `http://localhost:8000`; for production, set the GitHub Actions variable `VITE_API_URL` to the HTTPS URL of the deployed ContexA API Worker. The Pages workflow now fails fast if this value is missing.
- The frontend is configured for the clean Supabase-only sign-in screen (`VITE_AUTH_MODE=supabase`). Existing demo/local account records remain in the backend for a separately configured local-development profile, but they are not shown as production login choices. The offline `run-submission.sh` / `run-submission.bat` launchers explicitly override both frontend and backend auth mode to `local`, so the seeded judge accounts continue to work without touching Supabase.
- The live Supabase project's provider settings, custom access-token hook, URL allow-list, application role, session-reader view and initial users still need to be configured in the Supabase Dashboard. The production Render blueprint expects Supabase Postgres as `DATABASE_URL` and does not create a parallel Render database. This source-package step does not execute SQL against your hosted project. The connected Supabase account could not access the supplied project, and this runtime could not resolve the project hostname during a read-only Auth/JWKS probe, so live reachability and settings remain unverified.


## Cloudflare Pages deployment variables

Before enabling `.github/workflows/cloudflare-pages.yml`, configure these repository variables/secrets:

- Variable `ENABLE_CLOUDFLARE_PAGES_DEPLOY=true`
- Variable `CLOUDFLARE_PAGES_PROJECT=<your Pages project name>`
- Variable `VITE_API_URL=https://<your-deployed-ContexA-API-Worker-host>`
- Secret `CLOUDFLARE_API_TOKEN` with Pages deploy permissions
- Secret `CLOUDFLARE_ACCOUNT_ID`

The workflow fails before building if `VITE_API_URL` is missing or is not HTTPS. The Supabase URL and publishable key are read from the checked-in public `frontend/.env.production`; the project key is not a secret and is expected to be visible in browser assets.

## 8. Verify the supplied project's endpoint configuration

From the extracted project root, run the static check:

```bash
python ops/verify_supabase_project.py
```

After your machine has network access, verify the hosted Auth settings and JWKS endpoint with read-only requests:

```bash
python ops/verify_supabase_project.py --live
```

This command never prints the publishable key. It confirms endpoint reachability and the presence of an asymmetric public signing key; it does not replace a real sign-in test or the token-hook/RLS checks above.
