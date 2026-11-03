# ContexA + Supabase Auth

Supabase is used as an **external identity provider**, not as a second source of truth for ContexA authorization or workspace membership.

## What the current integration does

- Supabase password sign-in from the frontend when `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` (or the legacy `VITE_SUPABASE_ANON_KEY`) are configured.
- A single primary sign-in action in Supabase-only mode; hybrid mode keeps local login and exposes the organization identity option as a quiet secondary action.
- A one-time CLI command to provision the first ContexA workspace administrator without exposing a service-role key or allowing arbitrary public workspace creation.
- Access token signature validation using the Supabase project's JWKS, issuer, audience, expiry and verified-email claim.
- Optional AAL2 enforcement through `SUPABASE_REQUIRE_AAL2=true`.
- Links a verified Supabase subject to an existing ContexA account by immutable subject or verified matching email.
- Loads role, workspace and ContexA permissions from the existing ContexA `User` record. Supabase user metadata is never treated as an authorization source.
- Disables local password registration/login endpoints when `AUTH_MODE=supabase`.

This release does not claim to implement SAML/SCIM provisioning, WebAuthn/passkeys, or a full browser BFF with HttpOnly refresh-token cookies. Those should be separate follow-up milestones rather than represented as available controls.

## Supabase project configuration

1. Create a Supabase project in the required region and configure the project's Auth URL and allowed redirect/site URLs.
2. Require email confirmation. Configure SMTP with a verified sending domain for production.
3. Enable TOTP MFA and configure the organization's assurance policy. For deployments that require elevated assurance on every protected route, set `SUPABASE_REQUIRE_AAL2=true` and validate the expected `aal2` claim after your MFA flow has been tested.
4. Use the project's asymmetric JWT signing keys and publish the JWKS endpoint. Do not configure the backend with an unsigned or symmetric client-trusted token mode.
5. Supabase's standard access-token claim set does not guarantee an `email_verified` claim. ContexA deliberately fails closed unless it receives that claim. Apply [`custom_access_token_hook.sql`](custom_access_token_hook.sql), then enable `public.contexa_custom_access_token_hook` under **Authentication → Hooks → Custom Access Token**. The hook reads `auth.users.email_confirmed_at`; it does not trust editable user metadata. Verify that confirmed test users receive `email_verified: true` and unconfirmed users receive `false` before enabling production login.
6. Create the initial user in Supabase Dashboard → Authentication → Users. Confirm that the user's email is verified. Then provision the matching ContexA workspace administrator from the backend with `python bootstrap_supabase_admin.py --email admin@example.com --name "Workspace Admin" --workspace-name "Example Brand Team" --confirm-email-verified`. Run this only after the ContexA database migrations have been applied. The command creates one Brand Admin workspace, seeds the starter governance rules, and writes an audit event. It does not call Supabase Admin APIs and does not require a service-role key. Existing ContexA accounts should not be duplicated: a user with a matching verified email is linked on first successful Supabase sign-in. For additional team members, create/verify their Auth identity in Supabase first, then run the same command with `--workspace-id YOUR_WORKSPACE_ID --role Creator` (or `Manager` / `SME / Legal`) instead of `--workspace-name`; this adds the identity to the existing ContexA workspace without creating a new one.
7. Configure Cloudflare's allowed origins and the frontend environment variables below. For local frontend development, copy `frontend/.env.example` to `frontend/.env.local`. For Cloudflare Pages, set the same `VITE_*` values as build environment variables and trigger a new build after changing them.

## Environment variables

Backend:

```dotenv
AUTH_MODE=supabase
SUPABASE_AUTH_ENABLED=true
SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
SUPABASE_JWT_ISSUER=https://YOUR_PROJECT_REF.supabase.co/auth/v1
SUPABASE_JWKS_URL=https://YOUR_PROJECT_REF.supabase.co/auth/v1/.well-known/jwks.json
SUPABASE_JWT_AUDIENCE=authenticated
SUPABASE_PUBLISHABLE_KEY=sb_publishable_...  # public key; backend uses it for /logout
SUPABASE_SESSION_DATABASE_URL=postgresql+psycopg://contexa_session_reader:...@db.YOUR_PROJECT_REF.supabase.co:5432/postgres?sslmode=require
SUPABASE_SESSION_CHECK_REQUIRED=true
SUPABASE_REQUIRE_AAL2=false
SUPABASE_SESSION_CHECK_REQUIRED=true
SUPABASE_SESSION_DATABASE_URL=postgresql+psycopg://contexa_session_reader:REPLACE_WITH_RANDOM_SECRET@db.YOUR_PROJECT_REF.supabase.co:5432/postgres?sslmode=require
```

Frontend build-time public values:

```dotenv
VITE_AUTH_MODE=supabase
VITE_SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_YOUR_PUBLIC_KEY
# Or use the legacy browser-safe anon key if that is what the dashboard provides:
# VITE_SUPABASE_ANON_KEY=YOUR_LEGACY_ANON_KEY
```

The Supabase publishable/anon key is intended for browser use. **Never put the Supabase secret/service-role key, database password, AWS credentials, or JWT signing secret in any `VITE_*` variable.** The browser key is not a password; authorization is enforced by the backend and database policies.

## Database and RLS model

The production blueprint uses this Supabase project's PostgreSQL database as ContexA's primary application store. `DATABASE_URL` must use the `contexa_app` Transaction Pooler URI; `SUPABASE_SESSION_DATABASE_URL` separately uses the lower-privilege `contexa_session_reader` URI. The browser never connects to ContexA application tables through PostgREST: the API remains the only application data access layer. The browser uses Supabase Auth endpoints and sends its bearer access token to FastAPI. FastAPI verifies the JWT, maps its verified identity to a ContexA `User`, then applies ContexA workspace and role controls.

Do not expose ContexA private application tables through Supabase's auto-generated PostgREST API as a shortcut. Do not share the database owner/postgres credential with the browser. Keep `ENABLE_POSTGRES_RLS=true`, apply ContexA's migrations and workspace policies, and verify them using separate database roles and real concurrent workspace sessions before production launch.

Supabase Auth does not replace ContexA's authorization model. Never read `workspace_id`, role, plan, or permissions from untrusted `user_metadata` or browser-supplied headers. The canonical ContexA account record determines those values.

## Security checks before launch

- Confirm that a token from another Supabase project is rejected (issuer/JWKS mismatch).
- Confirm the Custom Access Token Hook emits `email_verified` from `auth.users.email_confirmed_at`.
- Confirm expired, malformed, wrong-audience and unverified-email tokens are rejected.
- Confirm an authenticated but unprovisioned Supabase user receives no ContexA workspace access.
- Confirm the initial Brand Admin was provisioned with `backend/bootstrap_supabase_admin.py` and that a second run refuses to create a duplicate.
- Confirm an existing account is linked only through its verified email or previously linked Supabase subject.
- Confirm changing Supabase user metadata cannot elevate a ContexA role.
- Confirm cross-workspace API requests fail even if the caller edits IDs in the request body.
Immediate sign-out revocation requires `SUPABASE_SESSION_CHECK_REQUIRED=true`, `SUPABASE_SESSION_DATABASE_URL`, and `SUPABASE_PUBLISHABLE_KEY`. The backend's `/api/auth/logout` calls Supabase Auth sign-out with the `local` scope, then its next authenticated request checks `(session_id, sub)` against the private `contexa_private.active_auth_sessions` view. A missing session returns 401; an unavailable session database returns 503 (fail closed). The session reader can select only the `(id, user_id)` projection, not the full `auth.sessions` table. The publishable key is browser-safe but must still be configured at runtime; the session database URI is a server-only secret. Never put the session URI or any secret/service-role key in a `VITE_*` variable. Verify the sequence with a real test user before production. In `local` auth mode the check defaults off; in `hybrid` and `supabase` modes it defaults on unless explicitly overridden.
- Keep Supabase JWT lifetime short (the Supabase default is commonly one hour; confirm the actual project setting) and ensure the application rejects expired tokens. Do not weaken issuer, audience, email-verification or algorithm checks to work around configuration errors.
- The backend readiness endpoint now performs a database `SELECT 1`; use it as the host health check. It does not prove that SMTP, object storage, malware scanning, Supabase Auth hooks, KMS or the Cloudflare edge are healthy. Run the corresponding scripts in `ops/` for those services.


## Clean activation checklist for an existing Supabase project

1. In Supabase **Project Settings → API**, copy the **Project URL** and **Publishable key**. A legacy `anon` key is also browser-safe. Never copy the `service_role` / secret key into frontend settings.
2. In **Authentication → URL Configuration**, add the local URL `http://localhost:5173` and your final public frontend URL. Add the exact callback/redirect URLs used by enabled providers.
3. In **Authentication → Sign In / Providers**, enable Email and require email confirmation. Configure custom SMTP before inviting external users.
4. In **Authentication → Signing Keys**, activate an asymmetric ES256 or RS256 signing key. The backend verifies tokens through the project's JWKS endpoint; legacy HS256-only projects are not accepted by this configuration.
5. In **SQL Editor**, run `custom_access_token_hook.sql`. Then go to **Authentication → Hooks → Custom Access Token**, enable `public.contexa_custom_access_token_hook`, and verify both a confirmed and unconfirmed test account's JWT claims.
6. Set backend `AUTH_MODE=hybrid` for a staged migration, or `AUTH_MODE=supabase` after the initial administrator is provisioned. Set `SUPABASE_URL`, `SUPABASE_JWT_ISSUER`, and `SUPABASE_JWKS_URL` in the backend host's secret/environment settings.
7. Set frontend `VITE_AUTH_MODE=supabase`, `VITE_SUPABASE_URL`, and `VITE_SUPABASE_PUBLISHABLE_KEY`. Set `VITE_SUBMISSION_MODE=false` in production. `VITE_API_URL` must point to the public Cloudflare Worker/API URL in production. The Cloudflare Pages GitHub workflow accepts the publishable key as a repository variable `VITE_SUPABASE_PUBLISHABLE_KEY`; a legacy anon key can still be supplied through the old secret name for compatibility.
8. Provision the initial ContexA admin. Sign in, then open **Trust Foundation** and refresh. Identity should show `supabase` and `configured` only when all backend settings are present.
9. Test wrong-project, expired, unverified-email, unprovisioned-user, role-tampering, cross-workspace and session-refresh cases before enabling real users.

### Which values may be shared for setup assistance?

The Project URL and Publishable key are browser configuration and can be shared for build configuration. Do not share the database password, `service_role` / secret key, JWT signing secret, SMTP password, AWS access keys, or any private signing key in chat or source control.
