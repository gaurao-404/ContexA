# ContexA Round 3 Release Notes

## Delivered
- Brand Truth Engine: versioned approved facts, validity windows, aliases, source quotation and optional document-level quotation verification.
- Evidence Ledger: scan-run fingerprints, finding-level citations, source and content quotations, rule version references and grounding states.
- Policy simulation: proposed regex impact scan across workspace documents, non-destructive preview, and approval-gated application as a new rule version.
- Risk routing: critical legal/claim issues to SME / Legal; pricing, asset and accessibility issues to Manager tasks.
- Brand Intelligence Lab connected to the backend: source fact create/approve, evidence ledger, evaluation history, policy simulation and benchmark.
- Rule version history view in the Rules screen.
- 50-case deterministic synthetic evaluation dataset and stored evaluation runs.
- Workspace-scoped brand asset registry with approval, archive, fingerprinting and private download.
- Structure-aware guideline chunking, page-aware hybrid keyword/vector retrieval and optional local embedding rebuilds.
- Self-service signup, optional SMTP email verification/password reset, one-time invitations, Argon2id password hashing and persistent login/signup throttles.
- Upload signature validation, Office archive inspection, image decompression limits and optional ClamAV scanning.
- Optional S3-compatible private object storage, workspace export/deletion controls and PostgreSQL workspace RLS policies.
- Tamper-evident SHA-256 audit hash chain and integrity verification.
- PostgreSQL additive migration reference and judge demo script.

## Test status
- Backend: 50 tests passed in a clean temporary SQLite database.
- Python compilation: passed.
- TypeScript/TSX syntax transpilation: passed for all frontend source files.
- CSS brace-balance validation: passed.
- Full frontend production build: not verified in this build environment.

## Benchmark interpretation
The included synthetic suite currently passes its seeded expected detections without false positives or false negatives. This validates regression behavior on the purpose-built fixture only. It is not a claim of 100% performance against arbitrary real-world brand documents. Use a blind human-annotated hold-out dataset for externally reported detection metrics.

## Important production items not included
Production still requires configured SMTP credentials for email verification/recovery, a live PostgreSQL staging validation of RLS, real S3/R2 credentials for durable private storage, a reachable ClamAV service if scanning is enabled, and operational hardening such as MFA/SSO, background workers, monitoring and backup/restore drills. See `ROUND3_PRODUCTION_GAPS.md`.

## Final hardening pass

- Added `token_version` session revocation for logout, password reset and member deactivation.
- Added request IDs, CSP and baseline browser security headers; auth API responses are no-store.
- Added per-account upload throttles and optional ClamAV Compose service profile.
- Added forced PostgreSQL RLS runtime verification and operator SQL checks.
- Added `boto3` to requirements for the configured S3-compatible adapter.
- Latest backend regression result: 47 passed. Vite production build and live external integrations remain staging tasks.


## Final staging/production hardening

- SMTP supports STARTTLS and implicit TLS with test preflight (`ops/check_smtp.py`).
- S3/R2 private storage has a write/read/delete preflight (`ops/check_object_storage.py`).
- ClamAV has PING + EICAR INSTREAM health verification (`ops/check_clamd.py`).
- PostgreSQL RLS verification checks forced RLS, policy predicates and tenant sentinel visibility (`ops/verify_postgres_rls.py`).
- Production Render profile is paid-capable and requires SMTP, private S3 and ClamAV; a separate free no-signup demo profile is included.
- GitHub Actions runs backend tests and the frontend build.
- See `ROUND3_REMAINING_RUNBOOK.md` for exact provider setup and commands.
