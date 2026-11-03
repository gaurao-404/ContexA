# ContexA Trust OS — production capability and operations guide

This release adds eight connected Trust OS capabilities to the existing ContexA governance application. The implementation deliberately distinguishes automated signals, source-backed evidence, and human decisions. A green machine check is not a legal opinion or proof that an arbitrary statement is true.

## Capability map

| Capability | Implemented workflow | Important boundary |
|---|---|---|
| Truth Drift Radar | Register HTTPS sources, fetch bounded snapshots, hash normalized source content, compare snapshots, create drift events, link affected claims/incidents, resolve events, and run scheduled scans. Expired approved facts can also be scanned. | A changed page/hash is a change signal. It does not by itself prove a brand claim is false. The monitor intentionally rejects private/non-global IPs, redirects, unsupported schemes, oversized responses and unsafe content types. Current source types are public HTTPS pages/files, not authenticated intranet sources. |
| Trust Passport | Issue only for a publish-ready document with no unresolved critical finding; bind the asset SHA-256, document/version metadata and review/policy data into an HMAC-SHA256-signed attestation; return a QR to a public verification route; revoke passports. | A passport proves that ContexA issued an attestation for the recorded asset digest and that the attestation has not been modified/revoked. It does not independently prove every claim is true. A changed file must be rehashed/reissued. Protect the dedicated signing key and back it up securely. |
| Multimodal inspection | Accept supported documents/images and media uploads within configured limits; extract document text/image information; use FFmpeg/ffprobe (installed in the production backend Docker image) to sample video frames and inspect media metadata; accept a user-provided transcript for audio/video; run deterministic brand/policy indicators and save an inspection record. | This is a screening pipeline, not a deepfake detector or complete speech-recognition service. Audio speech content is analysed only when a transcript is supplied. Video sampling is bounded (up to 12 frames, approximately one every five seconds); not every frame is inspected. OCR/model extraction can be incomplete and must be reviewed. |
| Governance agents | Run named, deterministic workflow steps for evidence, policy, claim and risk triage; persist steps/results; create review work for existing human approval flow. | Agents are workflow orchestrators, not autonomous publishers. They do not grant approvals, change a policy, or publish an asset. An enabled external LLM may assist existing product functions, but a run in this module should not be represented as an independent legal or truth determination. |
| Brand Digital Twin | Save a non-destructive scenario, compare proposed fact/policy values to approved facts and stored document content, and identify potentially affected documents for review. | The impact analysis is based on available stored facts/content and explicit matching. It can miss paraphrases, unindexed content, OCR errors and external campaign copies. Simulation never silently edits approved facts or published assets. |
| Indic language intelligence | Compare source/localized text for Unicode decimal-number parity, configured disclosure indicators and localized terminology hints across supported Indic language labels; store the review result. | It is not a general translation engine, semantic-equivalence model, cultural-sensitivity certification or substitute for a native-language reviewer. A numerical/disclosure mismatch is a useful deterministic signal; absence of a signal does not prove faithful translation. |
| Regulatory intelligence | Seed workspace screening references and allow authorized users to add scoped requirements with source URLs, jurisdictions, industries, trigger terms, required indicators and effective dates; produce persisted assessments and audit events. | Seeded requirements are reference summaries, not live synchronized law. Keyword screening produces `not_triggered`, `review_required` or `potential_gap`; it is not a legal applicability determination or certification. Administrators/legal reviewers must verify the source, current version, jurisdiction, exceptions and effective dates. `source_checked_at` remains empty until a real review is performed. |
| Incident command centre | Create incidents, set severity, relate source/documents, track status and resolution notes, and view incident history/linked drift events. | The workflow records investigation and ownership; it does not automatically remove third-party content or contact an external platform. |

## Data model and migrations

The additive Trust OS migration versions are:

- `2026_11_01_01_trust_os_capabilities`
- `2026_11_01_02_public_passport_index`

The first migration creates the new workspace-scoped Trust OS tables. The second adds the minimal public passport attestation index and backfills existing issued passports. Migration 02 is separate so deployments that previously applied migration 01 can upgrade without dropping/recreating tables.

The public passport endpoint cannot safely query tenant rows under PostgreSQL `FORCE ROW LEVEL SECURITY` without a workspace identity. For this reason, `public_passport_index` deliberately contains only the signed public attestation fields needed for QR verification and is not a workspace-readable data table. The original passport, document and review data remain workspace scoped. Revoke updates both the private passport and the public index. Keep the public index schema minimal; do not add private customer content, document text, reviewer email or workspace secrets to it.

Migration execution is invoked by the existing application startup migration hook. Before production rollout:

1. Take a tested PostgreSQL backup and test restore.
2. Deploy using the existing dedicated application database role (not superuser and not `BYPASSRLS`).
3. Confirm `ENABLE_POSTGRES_RLS=true` and run the supplied RLS verification scripts as the actual application role.
4. Confirm the migration table contains both versions and the public index backfill has completed.
5. Test a passport scan anonymously, then revoke it and confirm the public route reports revoked while a different workspace cannot read its private passport record.

## Required secrets and production settings

Set these in the FastAPI host's secret manager. Do not commit values to `.env`, a Pages build variable, `wrangler.jsonc`, GitHub or the ZIP.

```dotenv
APP_ENV=production
SECRET_KEY=<long-random-auth-secret>
TRUST_PASSPORT_SIGNING_KEY=<stable-random-secret-at-least-32-characters>
PUBLIC_APP_URL=https://app.example.com
TRUTH_DRIFT_CRON_TOKEN=<long-random-cron-bearer-token>
CLOUDFLARE_EDGE_ENABLED=true
CLOUDFLARE_ORIGIN_SHARED_SECRET=<same-value-as-worker-secret>
```

`TRUST_PASSPORT_SIGNING_KEY` is dedicated to passport signing and must be stable across restarts and deployments. Rotating it invalidates the ability to verify passports signed with the previous key unless you add a key-ID/keyring rotation procedure; do not casually rotate it. Keep a controlled backup. `PUBLIC_APP_URL` must be the public HTTPS frontend origin so QR links are valid outside local development.

`TRUTH_DRIFT_CRON_TOKEN` must match the Worker secret. The Worker calls the backend's internal due-scan endpoint every six hours using that bearer token. Configure the same origin shared secret on Worker and API only after the Worker can reach the API; direct browser-supplied headers are removed by the Worker and the Worker injects its secret.

## Cloudflare deployment for Trust OS

The existing Cloudflare split remains:

- Pages hosts the Vite/React application and SPA route `/verify/<public-id>`.
- Worker is the narrow `/api/*` reverse proxy and scheduled source-scan trigger.
- FastAPI remains on a Python-capable backend host.
- R2 is private S3-compatible storage for uploaded objects.

From `cloudflare/worker` after `wrangler login`:

```bash
npx wrangler secret put API_ORIGIN
npx wrangler secret put ORIGIN_SHARED_SECRET
npx wrangler secret put TRUTH_DRIFT_CRON_TOKEN
npx wrangler deploy
npx wrangler tail
```

Set `API_ORIGIN` to the FastAPI origin (not the Worker URL). Generate a long random `ORIGIN_SHARED_SECRET`; set the exact same value as backend `CLOUDFLARE_ORIGIN_SHARED_SECRET`. Generate a separate long random `TRUTH_DRIFT_CRON_TOKEN`; set the exact same value on the backend and Worker. Keep the cron token separate from the origin secret.

The Worker config includes the cron `0 */6 * * *`. After deployment, check `/edge-health` and `/api/health` through the Worker. In Worker logs, confirm each scheduled execution completes; in API logs, confirm requests reach `/api/internal/truth-drift/scan-due`. An empty scan result can be healthy when no sources are due. A source is not continuously monitored until it is registered and has a due/next-scan time.

Pages build settings remain `root=frontend`, `npm run build`, output `dist`. Set `VITE_API_URL` to the Worker/custom API hostname and include the Pages origin in Worker `ALLOWED_ORIGINS` and backend `ALLOWED_ORIGINS`. Pages `_redirects` must continue routing `/verify/*` to `/index.html`.

R2 stays private. Configure the backend's S3-compatible R2 endpoint, scoped bucket key and `REQUIRE_PRIVATE_OBJECT_STORAGE=true`; run `ops/check_object_storage.py`. Never serve user-upload buckets publicly to make passport QR verification work: passport verification uses the small signed public attestation endpoint, not public file access.

## API groups

The authenticated Trust OS API is under `/api`:

- `/trust-os/overview`
- `/truth-drift/sources`, `/truth-drift/events`, `/truth-drift/scan-expired-facts`
- `/trust-passports` and `/trust-passports/{id}/qr.svg`
- `/multimodal/inspect`, `/multimodal/inspections`
- `/agents/runs`
- `/digital-twin/simulate`, `/digital-twin/scenarios`
- `/indic/review`, `/indic/reviews`
- `/regulatory/requirements`, `/regulatory/assess`, `/regulatory/assessments`
- `/incidents`

Public QR verification is `GET /api/public/trust-passports/{public_id}`. The scheduled Worker-only endpoint is `POST /api/internal/truth-drift/scan-due`; it requires the configured cron bearer and, when edge lock is enabled, the shared origin secret. Regulatory assessment accepts a JSON body `{ "document_id": "..." }` or `{ "content_text": "..." }`; submitted content is not put in the URL query string.

## Operational controls to complete before production

1. **Secrets:** use a secret manager; rotate default/demo credentials; verify the dedicated signing key and cron token are present.
2. **Identity:** enable verified SMTP, MFA/SSO as required, correct role assignments and invitation lifecycle.
3. **Database:** use PostgreSQL with RLS and a non-bypass application role; validate restore, connection pool limits and migration rollback/forward strategy.
4. **Files:** private R2, lifecycle/retention, malware scanning with a private ClamAV service, MIME/file-size controls and backup/restore.
5. **Monitoring:** collect Worker logs, request IDs, backend error rates, queue/scan outcomes, failed passport verifications and incident ageing. Alert on repeated source fetch failures and drift backlog.
6. **Legal content:** have qualified counsel/local compliance owners review every jurisdictional requirement and record source verification/version dates; stale seed summaries must remain clearly marked.
7. **Human controls:** make sure high-risk findings require authorized approval and that no agent can publish/approve or silently modify evidence.
8. **Abuse controls:** tune Cloudflare WAF/bot controls, edge rate limits and backend per-user/per-IP throttles; test upload and inspection quotas under realistic concurrency.
9. **Privacy:** define retention/deletion, data residency and public passport disclosure. Publicly include only data explicitly approved for disclosure.
10. **Release:** deploy to staging, run the full CI suite, execute manual workflows below, and only then promote to production.

## Manual release acceptance tests

- Register two workspaces and prove users cannot read one another's source records, scenarios, inspections, passports, language reviews, requirements, assessments or incidents.
- Register a public HTTPS source with an approved-fact phrase, scan it, change the hosted test page, scan again and confirm a drift event is created. Confirm non-public IPs and redirects are rejected.
- Create a review-ready document, issue a passport, scan its QR anonymously, verify the SHA-256 attestation, revoke it and scan again. A document with an open critical finding must not receive a passport.
- Inspect a supported PDF/image. For video, confirm FFmpeg is installed and observe the bounded frame count. For audio, provide a transcript and confirm the UI explains that transcript extraction was supplied, not automatically recognized.
- Run agents and verify that they create review work but cannot approve/publish. Verify audit records.
- Simulate a change to an approved fact; inspect the affected-document list and confirm no underlying approved data changes.
- Run Marathi/Hindi/other supported Indic review with a changed numeral and a missing disclosure; confirm signals are visible and a human-review limitation is stated.
- Assess a sample document against enabled regulatory requirements; confirm requirement source/version and keyword-screening disclaimer are shown. Have an authorized legal reviewer verify seeded source material before operational reliance.
- Open, acknowledge, investigate and resolve an incident; verify the history and linked source/documents.
- Trigger the Worker Cron manually in staging or wait for its scheduled test window, and verify both Worker and API logs.

## Verified in this development environment vs deployment-dependent

The repository includes unit/API/security tests and Worker tests for the features described above. A passing local suite verifies the tested code paths only; it does not provision Cloudflare, SMTP, PostgreSQL, R2, ClamAV, DNS, legal content review or production observability. Those remain deployment and operational acceptance work. The React source can be syntax-transpiled without dependencies, but the Vite production build requires installing the frontend dependencies and must be run in CI or a network-enabled build environment.
