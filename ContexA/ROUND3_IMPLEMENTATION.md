# ContexA — Round 3 Complete Implementation

## Release scope

This release expands ContexA from a document checker into an evidence-driven brand governance workspace. It includes a source-of-truth fact registry, evidence ledger, versioned policy simulation, review routing, repeatable evaluation, brand asset management, hybrid guideline retrieval, public account lifecycle, tenant isolation controls, private storage adapters, audit integrity verification, and workspace data portability.

## 1. Brand Truth Engine

- Workspace-scoped fact registry for product names, prices, campaigns, claims, warranty terms and other approved facts.
- Facts move through `draft → approved → superseded`; revisions create new fact versions rather than silently overwriting approved values.
- Facts support aliases, currency/unit, validity windows, approver, source document, source quotation and source page.
- When an uploaded source document is selected, the backend checks the normalized supporting quotation against extracted document text before setting `source_verified=true`. An unlinked source remains a manual attestation.
- Active approved price and product-name facts participate in document scans and write-time copy checks. A mismatched price/product name is reported against the approved value. A price is not called stale without a current source-of-truth record.

## 2. Evidence Ledger

- Each scan records engine mode, ruleset fingerprint, status, finding count, evidence counts and duration.
- Each finding retains the rule-version ID used during its inspection.
- Evidence records preserve source type, source ID/version, source label, approved quotation, matched content quotation, locator and verification status.
- APIs expose evidence per finding, scan history and workspace-level evidence.
- Evidence without an approved source is marked as unverifiable/manual rather than treated as a confirmed violation.

## 3. Policy Simulation and Review Routing

- Brand Admins can test a proposed deterministic rule pattern against historical workspace documents without changing the active rule.
- Simulations store affected-document counts, match counts and representative excerpts.
- Applying a simulation requires a change note and produces a new immutable-by-application rule snapshot/version.
- Critical legal/claim findings route to SME / Legal; pricing, asset and accessibility findings route to Manager tasks.
- Review tasks support assignment, status and completion tracking.

## 4. Brand Intelligence Lab and evaluation

- The Insights workspace is connected to facts, evidence, review tasks, assets, retrieval search, policy simulation and benchmark history.
- Brand Admins can import a guideline, inspect page-aware chunks, search the guideline corpus and rebuild embeddings.
- The deterministic evaluation suite contains **50 synthetic seeded cases** across claim, terminology, tone, pricing and clean-content categories.
- Results persist TP/FP/FN, precision, recall, F1 and per-case details.
- The benchmark measures the configured deterministic engine only. It does not establish performance on arbitrary real-world documents or measure optional local LLM quality.

## 5. Brand asset registry

- Workspace-owned logo, font, template, color and campaign assets can be uploaded as drafts, approved, archived and downloaded.
- Assets are fingerprinted with SHA-256; duplicate bytes in a workspace are rejected.
- Upload type is checked against file signatures, not only the filename extension.
- The registry provides a source for future/assisted logo and visual compliance checks; it does not claim that all logo geometry, clearspace or image-background contrast is automatically verified.

## 6. Hybrid guideline retrieval

- Imported guideline text is split into structure-aware chunks with source filename, page number, heading context and SHA-256 source fingerprint.
- Search combines lexical matching with vector similarity. PostgreSQL uses full-text search and pgvector candidate retrieval before hybrid reranking; SQLite uses the offline application-level hybrid fallback.
- Default embeddings are deterministic hashed-token vectors so local/demo mode works without a model server. Optional local Ollama embeddings use `nomic-embed-text`; changing embedding models requires running the embedding rebuild endpoint.
- Chat models (Qwen/Nemotron) and embedding models have different roles. Do not assume a chat model automatically provides compatible vector embeddings.

## 7. Accounts, authentication and workspace access

- Self-service registration creates a separate workspace and grants its first user Brand Admin. Public registration cannot self-assign privileged teammate roles.
- Brand Admins invite Creator, Manager or SME / Legal members through one-time expiring invitation tokens; invitees choose their own password.
- Email verification and password recovery use hashed, expiring, one-time tokens and optional SMTP delivery.
- New passwords use Argon2id when installed; the verifier supports legacy PBKDF2 hashes and upgrades them after successful login.
- Login lockout, signup throttling and password-reset throttling persist hashed identity keys in the database.
- API operations enforce workspace matching. PostgreSQL deployments also enable/force workspace Row-Level Security (RLS) at startup when `ENABLE_POSTGRES_RLS=true`.
- `users`, `auth_action_tokens` and `login_attempts` are deliberately outside tenant RLS because authentication/token lookup occurs before a tenant transaction context is established; their access paths are narrowly scoped by user ID, email or one-time token hash.

## 8. Upload safety and private storage

- Upload handling limits request size and validates file signatures for supported PDFs, Office documents, text, images and fonts; Office ZIP containers are checked for unsafe paths/expansion.
- Image decoding has dimension/decompression safeguards. Optional ClamAV scanning can be enabled with `UPLOAD_SCAN_MODE=clamd` and a reachable private `clamd` service; it is not enabled by default.
- Storage adapter supports private local storage and S3-compatible object storage (AWS S3, R2, MinIO). Optional S3 server-side encryption is configurable per provider.
- Small demo deployments can store file bytes in PostgreSQL. For public/production deployments, configure private durable object storage rather than relying on ephemeral instance disks or large DB blobs.

## 9. Audit integrity and data portability

- New audit records form a workspace-scoped SHA-256 hash chain (`previous_hash` → `event_hash`). PostgreSQL advisory transaction locks serialize updates per workspace.
- `GET /api/audit/verify` checks the chain and reports legacy unhashed events. Hash chaining is tamper-evident after activation, not an external immutable ledger or protection against a privileged database administrator rewriting the entire chain.
- Brand Admins can export a ZIP containing JSON workspace records and original uploaded documents/assets. Password hashes, token hashes and storage paths are excluded.
- Brand Admins can delete a workspace only after supplying the current password and exact workspace name. This is irreversible and removes the workspace's users, documents, findings, facts, rules, evidence, assets and audit history.
- Expired authentication tokens and stale hashed rate-limit records are pruned on application startup. Content is not silently auto-deleted; use explicit document/workspace deletion and a separately approved retention schedule.

## 10. Principal API routes

| Capability | Route |
|---|---|
| Registration / login | `POST /api/auth/register`, `POST /api/auth/login` |
| Email verification / password recovery | `POST /api/auth/verify-email`, `POST /api/auth/password/forgot`, `POST /api/auth/password/reset` |
| Team invitations | `POST /api/invitations`, `POST /api/invitations/accept` |
| Facts | `GET/POST /api/facts`, `POST /api/facts/{id}/approve`, `POST /api/facts/{id}/revise` |
| Evidence | `GET /api/findings/{id}/evidence`, `GET /api/evidence-ledger` |
| Scan history | `GET /api/scans` |
| Policy simulation | `POST /api/policy-simulations`, `POST /api/policy-simulations/{id}/apply` |
| Review routing | `GET/PATCH /api/review-tasks` |
| Evaluation | `POST /api/evaluation/seed`, `POST /api/evaluation/run`, `GET /api/evaluation/runs` |
| Intelligence | `GET /api/brand-intelligence` |
| Guideline search | `POST /api/retrieval/search`, `POST /api/admin/rebuild-embeddings` |
| Brand assets | `GET /api/assets`, `POST /api/assets/upload`, `POST /api/assets/{id}/approve`, `GET /api/assets/{id}/download` |
| Audit integrity | `GET /api/audit`, `GET /api/audit/verify` |
| Workspace portability | `GET /api/workspace/export`, `DELETE /api/workspace` |

## 11. Database additions

New/expanded tables include `rule_versions`, `approved_facts`, `scan_runs`, `finding_evidence`, `policy_simulations`, `evaluation_cases`, `evaluation_runs`, `review_tasks`, `guideline_chunks`, `brand_assets`, `auth_action_tokens` and `login_attempts`. Existing tables gain fields for email verification, upload hashes/scanner status, embedding model identification, finding rule-version links and audit hash-chain values.

- `ops/round3_full_extension_postgres.sql` is the full additive DBA migration reference.
- `ops/round3_migration_postgres.sql` is the earlier Round 3-only migration reference.
- Runtime SQLAlchemy setup creates missing tables and performs small additive migrations; review and run the full SQL migration under a DBA-controlled process for managed PostgreSQL.

## 12. Test status and limits

- Current backend automated suite: **47 passed** (latest run).
- Tests cover registration/invitations/password reset, rate limiting, source-quote validation, workspace isolation, asset upload/download, private local/S3-adapter round trips, export/deletion, policy simulation, 50-case benchmark and audit-chain tamper detection.
- Python modules compile; all TypeScript/TSX files pass syntax transpilation; Render YAML parses.
- A full frontend production bundle was not verified because npm dependency installation timed out in this environment. Run `npm install` and `npm run build` from `frontend/` before deploying.
- Live PostgreSQL RLS behavior, real SMTP delivery, real S3/R2 credentials and a running ClamAV daemon are configuration-dependent integrations and were not exercised against external services here.
- A 50-case synthetic benchmark is not a blind real-world evaluation. For competition claims, add independently labelled hold-out documents and report category-level precision/recall and false-positive rates.
- Visual logo clearspace, logo distortion and contrast on complex imagery still require a dedicated visual model or human review; text parsing alone cannot prove these conditions.
- Durable background queues, SSO/MFA, refresh-token rotation and per-device sessions, external error monitoring, backup/restore drills and independent security testing remain future hardening work. Token-version revocation, CSP and baseline security headers are implemented.

## Additional production-hardening pass

- Added forced PostgreSQL RLS verification across all 29 workspace-owned tables (including the Enterprise Trust Foundation tables). Production startup rejects a database role with superuser or `BYPASSRLS` privileges. `ops/verify_postgres_security.sql` provides an operator-side check.
- Added security response headers (CSP, HSTS in production, frame denial, MIME sniffing protection, referrer/permissions policies), no-store for auth endpoints and request IDs.
- Added per-account upload throttling across documents, guidelines and brand assets.
- Added account token-version invalidation: logout, password reset and member deactivation revoke previously issued access tokens.
- Added optional ClamAV Docker Compose profile; when enabled, uploads fail closed if the daemon is unavailable or flags a file.
- Added `boto3` to backend requirements and private-bucket validation for S3 reads/deletes.
- Added clean-checkout test initialization (the test suite now boots the app before touching its database).
