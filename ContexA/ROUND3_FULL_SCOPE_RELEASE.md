# ContexA Studio — Round 3 Full-Scope Release

## Included capabilities

### Brand intelligence and evidence
- Workspace-scoped approved facts for prices, product names, warranty terms, campaign details and claims.
- Fact validity windows, aliases, source references, approval status and revision history.
- Exact supporting-quotation matching against uploaded source documents.
- Finding-level evidence ledger with rule-version references, scan fingerprints, page/locator context and explicit grounding status.
- Structure-aware guideline chunks with heading/page/document/hash metadata.
- Hybrid lexical/vector retrieval; deterministic offline embedding fallback and optional local Ollama embeddings.
- Workspace-scoped asset registry with draft, approved and archived states, checksums and private download support.

### Policy governance and review
- Rule version snapshots and historical version lookup.
- Proposed regex/policy simulation against previously uploaded workspace documents.
- Change-note and authorization gate before policy activation.
- Risk-based review-task assignment for legal/claim and pricing/asset/accessibility categories.
- Review task status/assignment lifecycle.

### Evaluation and intelligence
- 50-case synthetic seeded evaluation suite.
- Per-case true/false-positive/false-negative results and aggregate precision, recall and F1.
- Persisted evaluation run history and Brand Intelligence metrics.
- The benchmark is a repeatable regression fixture, not a real-world generalization claim.

### Accounts, privacy and administration
- Self-service registration creates a separate workspace; first member is its Brand Admin.
- Optional SMTP email verification and password recovery using hashed, expiring, one-use tokens.
- One-time team invitations; invitees set their own password.
- Argon2id password hashing with legacy PBKDF2 hash upgrade.
- Persistent signup/password-reset/login throttling and temporary login lockout.
- Workspace access enforcement in API queries and PostgreSQL RLS policies for workspace-owned tables.
- Private local/S3-compatible object storage adapters; signature validation, archive path/expansion checks, image dimension safeguards and optional ClamAV scanning.
- Workspace ZIP export and password/name-confirmed workspace deletion.
- SHA-256 audit hash chain and audit integrity verification.

### Experience and delivery
- Clean Minimal / Obsidian glass UI, high-contrast logo/buttons, 16 colorways and motion profiles.
- Optional local Ollama contextual checks and optional local embedding generation; deterministic rules-only mode works without Ollama.
- Single-service Docker/Render setup, PostgreSQL Blueprint and full additive DBA migration reference.
- Run scripts for local development and submission mode.

## Validation performed for this release

- Backend: 50 tests passed in a clean temporary SQLite database (`cd backend && python -m pytest -q`).
- Python module compilation passed.
- All 5 `.ts` / `.tsx` source files passed TypeScript transpile syntax checks.
- CSS brace-count sanity check passed.
- `render.yaml` and `docker-compose.yml` parse as YAML.
- Release file layout and archive integrity checked.
- A full frontend production bundle was not verified: npm dependency installation timed out in the authoring environment. Run `npm install` and `npm run build` inside `frontend/` before deployment.

## External systems not live-tested here

Real SMTP, managed PostgreSQL RLS behavior, an external S3/R2 bucket, and ClamAV require credentials/services and were not exercised against external infrastructure. The S3 adapter was tested with a fake client plus the local storage adapter. RLS SQL and runtime policies are included but must be verified with a least-privilege staging database role. The included synthetic benchmark must not be presented as real-world accuracy.

## Recommended evaluator walkthrough

1. Create a workspace, sign in as its Brand Admin, and upload a fictional product price book.
2. Add an approved price fact using a supporting quote from the uploaded file.
3. Submit promotional copy with an outdated price or unsupported superlative.
4. Open the resulting finding and show its rule version and evidence record.
5. Propose a terminology pattern change, simulate it against old documents, and apply it with a change note.
6. Inspect review tasks and rule history.
7. Run the 50-case synthetic evaluation and explain its limitations.
8. Verify the audit chain and export workspace data using non-sensitive demo content.
