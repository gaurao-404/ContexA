# Deploy ContexA Studio — Round 3 Complete

This project is configured as a single Render Docker web service: the Docker build compiles the Vite frontend, then FastAPI serves the static frontend and `/api/*` routes from one public URL. PostgreSQL is provisioned by the Render Blueprint.

## 1. Prepare the repository

1. Extract the release ZIP.
2. Create an empty GitHub repository.
3. From the extracted project root (the directory containing `render.yaml`, `backend/`, and `frontend/`), run:

   ```powershell
   git init
   git add .
   git commit -m "Release ContexA Round 3"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/contexa-studio.git
   git push -u origin main
   ```

4. Confirm the GitHub repository root contains `render.yaml`, `backend/`, `frontend/`, `ops/`, and the run scripts.

## 2. Create the hosted service

1. Open https://dashboard.render.com/.
2. Choose **New → Blueprint**.
3. Connect the repository and apply the `render.yaml` Blueprint.
4. Render builds the frontend and backend in one Docker image and provisions the PostgreSQL database.
5. Wait for the health check at `/api/health` to pass, then open the service URL shown in Render.

The ZIP does not itself create a public URL. Render assigns the URL after deployment from your account.

## 3. Configure public account registration

The Blueprint sets `EMAIL_VERIFICATION_REQUIRED=true`. Before expecting public users to register successfully, configure these Render environment variables:

- `PUBLIC_APP_URL`: exact deployed HTTPS URL, no trailing slash.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`.
- `SMTP_FROM_EMAIL`, `SMTP_FROM_NAME`, and `SMTP_USE_TLS`.

The API intentionally fails closed when email verification is required but SMTP is not configured. This avoids creating accounts that cannot verify their email. Never publish SMTP credentials or `SECRET_KEY` in source control.

The first registered user owns their new workspace and becomes its Brand Admin. Team members should be invited with one-time tokens; invitees set their own password. Public registration cannot choose a role in an existing workspace.

## 4. Configure secure persistence

The Blueprint provisions PostgreSQL and sets `DATABASE_URL`. The app enables tenant RLS when `ENABLE_POSTGRES_RLS=true`; verify that setting is present in the deployment configuration. Before production use:

1. Review and apply `ops/round3_full_extension_postgres.sql` with a DBA-controlled migration process.
2. Use a dedicated application DB role that is neither superuser nor has `BYPASSRLS`. The current application enables policies at startup, so this role needs ownership/DDL rights on protected tables; `FORCE ROW LEVEL SECURITY` ensures table owners remain subject to the policies. Verify behavior using two test workspaces.
3. Configure a private S3-compatible bucket (AWS S3, Cloudflare R2 or MinIO) using `S3_BUCKET`, `S3_REGION`, `S3_ENDPOINT_URL` (when needed), `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_PREFIX`, and `S3_FORCE_PATH_STYLE` as appropriate.
4. Configure object-store lifecycle/backup, database backups and a retention policy.

The current Render Blueprint defaults to database-backed upload bytes for demonstration. This is convenient for a small demo but is not the recommended long-term storage design for large customer files. Do not rely on `/tmp` or ephemeral service disks for durable documents.

## 5. Optional integrations

- **Ollama:** disabled in the Render Blueprint. A local Ollama instance on a developer's PC is not reachable by public users. For hosted contextual AI, use a securely reachable model service and do not expose an unauthenticated Ollama port. Deterministic rules work without AI.
- **Embeddings:** offline hashed-token embeddings work without Ollama. For semantic embeddings, set `OLLAMA_EMBEDDINGS_ENABLED=true`, configure a reachable Ollama service with `nomic-embed-text`, and rebuild the workspace embeddings after changing models.
- **ClamAV:** optional. Set `UPLOAD_SCAN_MODE=clamd` only when a reachable private `clamd` service is configured and tested. Local Compose includes an opt-in `security` profile.
- **PostgreSQL RLS:** production startup enables and verifies forced RLS. Run `ops/verify_postgres_security.sql` with the application's database role and confirm `rolsuper=false`, `rolbypassrls=false`, and all workspace tables show `rls_enabled=true` / `force_rls_enabled=true`.
- **S3-compatible storage:** optional for local demo, recommended for durable multi-instance deployments.

## 6. Smoke test after deployment

1. Open `https://YOUR-RENDER-URL/api/health`; expect `{"status":"ok"}`.
2. Open the application and create a new account using an email address you can access.
3. Verify the email using the configured email link.
4. Upload a test PDF/DOCX and add an approved fact with an exact supporting quotation.
5. Review a deliberately incorrect test document, inspect its Evidence Ledger, simulate a rule change, and run the seeded evaluation.
6. Create a second workspace account and confirm it cannot access the first workspace's content.
7. Verify `/api/audit/verify` and test workspace export using non-sensitive test data.

## 7. Important limits

This is a competition/early-beta release, not a security-certified commercial SaaS. The code includes email verification/recovery and SMTP hooks, PostgreSQL RLS policies, upload validation and optional scanning, S3-compatible storage, workspace isolation, data export/deletion and a tamper-evident audit chain. However, this environment did not exercise real SMTP delivery, a real S3/R2 bucket, live PostgreSQL RLS behavior, or ClamAV. The seeded 50-case benchmark is synthetic and not a real-world accuracy guarantee. A complete frontend production build must be verified during deployment because npm installation timed out in the authoring environment.

Before processing confidential content, conduct a security review, test backup/restore and tenant isolation on the actual database role, configure durable storage and email, and implement MFA/SSO, refresh-token rotation, monitoring and background parsing workers as required. Token-version revocation and baseline CSP/security headers are already included.
