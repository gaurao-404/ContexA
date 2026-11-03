# ContexA — Production Readiness: Completed Hardening and Remaining Risks

## Implemented in the application

- Multi-workspace registration, invitations, verification links, password recovery, Argon2id hashing with legacy upgrade and persistent account throttling.
- Workspace-scoped API authorization and PostgreSQL RLS enable/force/policy verification; the app rejects PostgreSQL superuser/BYPASSRLS roles in production.
- File-signature/Office archive validation, upload limits and optional fail-closed ClamAV INSTREAM scanning.
- Private local or S3-compatible object storage adapters with bucket/key restrictions; `boto3` is declared.
- SMTP sending supports STARTTLS and implicit TLS; production rejects plaintext configuration.
- Workspace data export/deletion controls, password-confirmed destructive flow and a tamper-evident SHA-256 audit chain.
- Preflight scripts: `ops/check_smtp.py`, `ops/check_object_storage.py`, `ops/check_clamd.py`, `ops/verify_postgres_rls.py`.
- Separate Render profiles: `render.demo.yaml` for temporary no-signup judging and `render.yaml` for paid-capable public accounts with SMTP, private S3-compatible storage and private ClamAV.
- Cloudflare deployment source: Pages configuration, Workers API gateway with origin allowlisting/request IDs/edge throttling, optional shared-secret origin lock, R2-compatible storage configuration, Turnstile client + server verification, optional AI Gateway routing, and Settings readiness indicators.
- GitHub Actions runs backend regression tests, Cloudflare Worker smoke tests, and the frontend production build on repository pushes/pull requests; Worker deployment is an opt-in workflow requiring Cloudflare secrets.
- Hackathon evaluator assets: a five-minute judge runbook, seedable deterministic demo scenarios, and a Cloudflare deployment guide.

## Requires deployment owner configuration and live verification

These cannot be honestly marked complete without the owner's accounts, credentials and target infrastructure:

1. **SMTP:** configure a real sender/domain, TLS credentials, DNS sender authentication (SPF/DKIM/DMARC where available), then run `python ops/check_smtp.py --to <test-recipient>` and test signup verification plus password reset end-to-end.
2. **Private object storage:** provision a private S3/R2 bucket, bucket-scoped credentials, lifecycle/versioning and encryption, then run `python ops/check_object_storage.py` and test authorized download/export/delete. Cloudflare R2 supports the S3 API; use region `auto` and its account endpoint. See https://developers.cloudflare.com/r2/get-started/s3/.
3. **ClamAV:** provision the private daemon and confirm startup/health, run `python ops/check_clamd.py`, and test that clean uploads pass, EICAR test content is rejected, and scanner outage fails closed.
4. **PostgreSQL RLS:** deploy using a non-superuser, non-BYPASSRLS application role; run both SQL and Python RLS checks against staging. Review grants and make sure the application role can apply schema/policy migrations but is still subject to forced RLS.
5. **Public deployment:** use paid-capable Render resources for real account onboarding. Render Free web services block outbound SMTP ports 25/465/587, and Free Postgres expires after 30 days; free profile is for temporary no-signup demos only. See https://render.com/docs/free.

## Remaining independent product/security work

- MFA/OIDC SSO, refresh-token rotation and per-device session management.
- Configure Cloudflare account-level WAF/bot rules and tune origin protections. The bundled Worker provides approximate per-location rate limits; retain backend/database throttles for authoritative controls and use Durable Objects or a stricter backend limiter if a global hard quota is required.
- Sandboxed document parsing workers and durable background queue for large files.
- Structured logs, request correlation, metrics, tracing, error reporting and alert routing.
- Automated encrypted backups and repeated database + object-store restore drills.
- External immutable audit checkpoint anchoring; the current SHA-256 chain is tamper-evident but not a write-once independent ledger.
- Human-labelled blind evaluation set of 50–100+ real documents, with category-specific metrics and reviewer time measurement. The seeded 50-case benchmark is a deterministic smoke test, not a real-world accuracy claim.
- Independent dependency, secret, security and penetration testing before commercial handling of confidential data.
- Review retention/deletion SLAs, privacy notices, DPA/subprocessor disclosure and incident response procedures with the deployment owner.

## Verification status in this build environment

- The Enterprise Trust Foundation release regression suite: 77 backend tests passed on a clean SQLite database; Cloudflare Worker smoke suite: 6 passed. Frontend TypeScript/TSX syntax was parsed successfully, but Vite production build remains unverified because dependency installation timed out. Terraform formatting/provider validation are configured in GitHub Actions and were not run locally because Terraform is not installed in the authoring environment.
- Cloudflare Worker smoke suite: 4 passed; Worker JavaScript syntax check passed.
- Python compile checks: passed.
- Frontend TypeScript/TSX syntax transpilation: passed for 5 TS/TSX source files (syntax only; dependency/type checking is not included).
- Render and GitHub Actions YAML parsing: passed; Wrangler configuration JSON parse passed.
- Full Vite production build: not verified here because `npm install` timed out while fetching from the npm registry. TypeScript's full project check could not resolve React/Vite dependencies for the same reason. CI is configured to install dependencies and run the build after the repository is pushed to GitHub.
- Docker image/Compose runtime: not verified here because Docker is not installed in this execution environment.
- Live PostgreSQL, SMTP, S3/R2 and ClamAV preflight checks: not run because no deployment credentials or provider services were supplied.
