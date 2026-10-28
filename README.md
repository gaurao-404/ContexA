## Publish a public working link

See [DEPLOY_PUBLIC_LINK.md](DEPLOY_PUBLIC_LINK.md) for a one-service Render deployment. The UI and API are served from the same public URL, and demo mode runs without Ollama or a cloud API key.

# ContexA Studio — Clean Minimal Edition

The latest UI revision simplifies navigation and removes duplicate labels, replaces the old bar symbol with a solid ContexA mark, adds subtle page/tab and palette transitions, and fixes all 16 theme token sets so selected palettes actually change the workspace. The no-Ollama Submission Mode remains available via `run-submission.bat`. See [CLEAN_MINIMAL_EDITION.md](CLEAN_MINIMAL_EDITION.md) for the release notes and validation status.

---

## Frontend build fix (October 2026)

The duplicated `documentPositions` declaration in `frontend/src/GovernanceScene3D.tsx` has been removed. Run `npm install` and `npm run build` from the `frontend` folder to verify/build the frontend.

# ContexA Studio — Obsidian Champagne Edition (Submission-safe)

ContexA is a pre-publication brand-governance workspace based on the supplied **ContexA Platform Implementation Plan v2.4**. It combines deterministic content checks, optional grounded AI review, a findings/reviewer workflow, a spatial PDF preview, governance insights, role-based access controls, and audit exports.

> **Release scope:** This is a runnable full-stack MVP and deployment starter with the Atelier editorial-glass UI refresh, not a security-certified enterprise release. Seeded users/passwords and the default secret are for local demonstrations only. Before any real customer content is processed, replace demo credentials/secrets, configure TLS and managed secrets, review data-retention requirements, and perform a security assessment.

## Spatial 3D governance scene (Motion Edition)

The dashboard hero now uses a dependency-free real-time 3D projection scene rather than a CSS light/pulse effect. A faceted 20-face icosahedral crystal rotates around three axes; three orbital planes sit at different inclinations; four labelled control chips (CLAIMS, POLICY, ACCESS and PRICE) plus three perspective-projected document tiles (PDF, PPT and DOC) travel along separate 3D paths, with depth ordering, tethers and front/back movement. The drawing is animated on Canvas and reacts subtly to pointer movement. A selectable Calm / Studio / Cinematic motion profile controls speed without changing the review workflow. It uses no additional npm package. `prefers-reduced-motion` freezes the scene to a stable pose and stops the animation loop.

Open `/preview.html` from the running local Vite server to see the core dashboard design, or `/palette-motion-lab.html` for the interactive visual preview: all sixteen palettes are clickable, and the motion selector changes the 3D scene's movement speed. The visual preview uses illustrative sample values. The real application dashboard is at `/` and displays live API data.

## Obsidian glass interface and colorways

The presentation default is **Obsidian Champagne**: near-black mineral glass, champagne-gold actions, coral risk accents and periwinkle refraction. Settings includes sixteen art-directed colorways—Obsidian Champagne, Ember Atelier, Glacier Signal, Orchid Nocturne, Cobalt Flux, Jade Noir, Solar Flare, Rose Quartz, Ocean Depth, Acid Punk, Silver Mist, Kyoto Neon, Copper Bloom, Arctic Opal, Volcanic Glass and Monsoon Iris—saved in this browser and reflected by the 3D governance scene. The palette system shifts ambient surfaces as well as accent colors. The glass material spans navigation, login, bento dashboard panels, review canvas, rules, audit, team access, forms and modal surfaces. The successful sign-in uses a short, 3D-scene-led workspace reveal; navigation tabs enter with a restrained spatial transition and section-tinted accent sweep; palette changes use a single chromatic wash. Copy was tightened to remove duplicated micro-labels and repeated status text. These transitions respect `prefers-reduced-motion`. Calm, Studio and Cinematic motion profiles are persisted locally; operating-system `prefers-reduced-motion` always takes priority. Theme choice uses the v3 preference key and falls back to a compatible earlier saved theme.

**Keyboard shortcuts:** `Ctrl+K` / `⌘K` opens global search; `/` focuses search when you are not already typing; `Esc` closes search suggestions.

## Expanded palettes and motion controls

Settings → Choose a colorway now offers sixteen distinct schemes: Obsidian Champagne, Ember Atelier, Glacier Signal, Orchid Nocturne, Cobalt Flux, Jade Noir, Solar Flare, Rose Quartz, Ocean Depth, Acid Punk, Silver Mist, Kyoto Neon, Copper Bloom, Arctic Opal, Volcanic Glass and Monsoon Iris. Palettes alter the scene colors and ambient glass theme, not just the primary button. Settings → Choose your motion profile offers Calm, Studio and Cinematic speeds for the 3D governance scene and associated motion treatment. All choices persist in the browser. The standalone `/palette-motion-lab.html` page gives evaluators a no-login visual preview with clickable themes and motion profiles; all metrics shown on that standalone page are explicitly illustrative.

## Included features

- **Workspace dashboard:** integrity/compliance score, document and finding totals, recent activity, severity metrics.
- **Content library:** upload PDF, DOCX, PPTX, TXT, Markdown, PNG/JPG/TIFF/BMP; search/filter content; rescan and remove documents according to permissions.
- **Inspection engine:** configurable regex-based brand rules, absolute/quantified-claim detection, legal-disclaimer check, price/discount-reference signals that require validation against the current source of truth, PDF text-contrast estimation against white, PowerPoint image-alt-text checks, and contextual review through an optional local Ollama model (no API key), with an optional cloud fallback only if separately configured.
- **Write-time copy check:** the Overview's `Check this copy` action posts copy to `POST /api/check-copy`, runs fast deterministic scans against active workspace rules, and returns rule IDs, source guideline names, reasoning and suggested fixes. It does not call the LLM for inline checks.
- **Risk coverage, with honest boundaries:** the starter rules can flag unsupported quantified claims and superlatives, pricing/promotion mentions that need current-source validation, prohibited or incorrect product-name patterns when configured, terminology/off-tone rules when authored, PDF text contrast estimates, and PowerPoint missing/generic image alt text. Logo placement/clearspace and image-overlay contrast require a calibrated visual workflow and/or human confirmation; they are not falsely represented as fully solved by text checks.
- **Guideline import:** Brand Admins can import a text-based PDF, DOCX, PPTX, TXT or Markdown guide from Brand guidelines. ContexA extracts reviewable clause candidates and records the original source filename. Imports start paused and are never automatically treated as approved rules; the owner reviews, edits, sets enforcement patterns where appropriate and activates each rule. A clause without a detector pattern cannot produce deterministic inline matches unless a local model is available for contextual review; the UI labels imported clauses that still need a pattern or an enabled contextual review path.
- **Visual review boundary:** PowerPoint pictures with missing or generic filename-only alt descriptions are flagged. PDF text contrast is estimated against white. Logo cropping/clearspace, text over image backgrounds and whether a price is truly current still need visual review and/or an authoritative connected source of truth; the app does not claim to infer these facts from text alone.
- **Grounded AI guard:** prefers an Ollama model running locally. It only accepts IDs from retrieved active rules and checks each quoted finding against uploaded text; results with invalid IDs or unsupported quotes are marked *Unverifiable*. No cloud API key is required. If local AI is absent, deterministic checks still run and the interface tells you that contextual verification did not run.
- **Review studio:** page preview, finding list, severity labels, recommended remediation, accept/dismiss/edit actions, mandatory reason for dismissals, and exact replacement text saved for revisions. The uploaded original is not silently altered.
- **Publication gate:** sign-off permissions are role-controlled; open critical findings block publication unless the documented sign-off/override rules are satisfied.
- **Rules workspace:** admin-only rule creation/update and activation, including custom regex patterns.
- **Governance insights:** guideline-clarity metrics and recurring findings by rule/category.
- **Audit & export:** server-recorded review events; JSON governance report and CSV findings export.
- **Authentication/RBAC:** signed bearer tokens and four demo roles enforced by the API.
- **Persistence choices:** SQLite by default for a quick local run; PostgreSQL + pgvector through Docker Compose for a deployment-style setup.

## Quick start (Windows)

Requirements: Python 3.11+ (3.12 recommended), Node.js 20+ (22 recommended), and npm. Install Tesseract OCR if image/scanned-PDF OCR is required. Native selectable-text PDF inspection does not require OCR.

1. Extract the project folder.
2. For a presentation, **double-click `run-submission.bat`**. It forces `APP_ENV=demo`, disables Ollama and all cloud AI providers for that process, then starts the API and web app in separate terminal windows. It reuses installed dependencies on repeat launches. To enable optional local AI later, run `run-dev.bat` instead.
3. Open **http://localhost:5173**. API docs are at **http://localhost:8000/docs** and health is **http://localhost:8000/api/health**.

If your environment uses an execution policy or cannot run the launcher, run the commands in the manual section below.

## One-click submission launch (Windows)

Use `run-submission.bat` when handing in the project or presenting it on a computer where Ollama may not be running. It deliberately disables all AI provider calls and displays a **SUBMISSION MODE · RULES ONLY** indicator in the app. Deterministic checks, demo sample seeding, uploads, finding review actions, audit events, exports and publication gates remain active. The first launch needs Python/Node dependencies to be installed; subsequent launches reuse the local environments. No Ollama process or API key is needed.

For macOS/Linux, run `./run-submission.sh`. The submission launcher does not start or configure Ollama. Optional local AI remains available through `run-dev.bat` / `run-dev.sh` and `.env` when you are developing beyond the no-key submission path.

## Manual local start (Windows PowerShell)

From the `ContexA_MVP` directory:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

## Manual local start (macOS/Linux)

From the `ContexA_MVP` directory:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
cp .env.example .env
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

The local SQLite database is created automatically at `backend/contexa.db` and seeded with the four demo accounts and starter rules. It is generated runtime state and is not included in the source archive.

## Demo accounts

| Role | Email | Password |
|---|---|---|
| Brand Admin | `admin@contexa.local` | `ContexA!2026` |
| Manager | `manager@contexa.local` | `Manager!2026` |
| SME / Legal | `legal@contexa.local` | `Legal!2026` |
| Creator | `creator@contexa.local` | `Creator!2026` |

Use these accounts only for local demonstration. The UI login screen also provides one-click selection of each role.

## Submission mode — Ollama is not required

The project defaults to **deterministic rules-only mode**. `run-submission.bat` and `run-submission.sh` explicitly force `OLLAMA_ENABLED=false`, `AI_VERIFICATION_ENABLED=false`, and an empty cloud API key, regardless of values in an existing `.env` file. In this profile the backend does not probe Ollama, start a model, download a model, or call a cloud AI provider. Upload, deterministic brand checks, findings, reviewer actions, audit history, CSV/JSON exports and publication gates remain usable. The UI explicitly labels when contextual AI did not run. This mode is recommended for live submissions where the evaluation computer may not have a local model installed.

On an empty demo workspace, sign in as Brand Admin and click **Prepare demo workspace**. The top navigation shows **SUBMISSION MODE · RULES ONLY** so evaluators can see that the demo does not depend on a local AI service. ContexA creates three clearly named sample text assets (campaign claim, product naming, and price/promotion), runs the same deterministic inspection rules used for uploaded content, stores the findings and audit records, and never calls an AI provider. The action is repeatable and does not duplicate those sample filenames. The sample records are illustrative, not real brand/pricing data. Demo seeding is disabled when `APP_ENV` is set to production.

## Optional local AI — no API key required

To add local contextual tone/claim review later without a cloud API key:

1. Install [Ollama](https://ollama.com/download) for your OS.
2. In a terminal, download the default model once:

   ```bash
   ollama pull nemotron-mini:4b
   ```

3. Keep Ollama running. Its desktop app normally starts the local service; if needed run `ollama serve` in a terminal.
4. In `.env`, set `OLLAMA_ENABLED=true` and `AI_VERIFICATION_ENABLED=true`, then start/restart ContexA and visit **Settings → Local AI engine**. The page reports whether the service and model are available. For submission without Ollama, keep both flags `false`.

The default endpoint is `http://127.0.0.1:11434` and the default model is `nemotron-mini:4b`. Override `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_ENABLED`, or `OLLAMA_REQUEST_TIMEOUT` in `.env` if necessary. The model download is a one-time local download, may be several GB, and needs enough RAM for inference. Ollama uses the model locally; no cloud AI API key or per-token cloud charge is required.

**Fallback behavior:** if Ollama or the model is unavailable, ContexA continues in rules-only mode and explicitly says contextual checks did not run. It does not mark content compliant simply because a model is missing. Pricing freshness still needs a current authoritative price source; claim substantiation needs supporting evidence; logo placement and contrast over imagery need appropriate visual verification or human review. An existing `ANTHROPIC_API_KEY` is an optional legacy fallback, not required for the local path.

If the backend itself is inside Docker while Ollama runs on the host, set `OLLAMA_BASE_URL=http://host.docker.internal:11434` in `.env` and confirm your local Ollama service accepts host/container access.

## PostgreSQL + pgvector (Docker)

Requirements: Docker Engine/Desktop and the Compose plugin.

```bash
cp .env.example .env
# Edit .env and set a strong POSTGRES_PASSWORD and SECRET_KEY first.
docker compose up --build
```

Open the same web/API URLs as above. Compose starts pgvector/PostgreSQL, FastAPI, and Vite; the database and uploaded-file storage are persisted in named Docker volumes. Do not expose this default development Compose configuration directly to the public internet.

## Test and validation

From the project directory with backend dependencies installed:

```bash
cd backend
python -m pytest -q
```

The shipped suite covers upload/review/publish gating, role restrictions, exact edit recording, exports/audit events, rendered PDF preview, copy checking against active rules, paused guideline imports, PowerPoint alt-text findings, parsing, and inspection scoring. Run it against your deployment database configuration before releases. `pytest.ini` also configures the local Python import path for direct `pytest` invocation.

## Core API routes

| Route | Purpose |
|---|---|
| `POST /api/auth/login`, `GET /api/auth/me` | Login/session identity |
| `GET /api/dashboard`, `GET /api/insights` | Dashboard and governance metrics |
| `POST /api/check-copy` | Authenticated write-time deterministic copy check |
| `POST /api/demo/seed` | Brand Admin-only, development/demo sample-workspace setup; deterministic-only, repeatable, no Ollama calls |
| `POST /api/guidelines/import` | Import policy files as paused rule candidates (Brand Admin only) |
| `GET/POST /api/documents`, `POST /api/documents/upload` | Content library and upload |
| `GET /api/documents/{id}` | Findings and review detail |
| `GET /api/documents/{id}/preview/{page}` | Rendered page preview |
| `POST /api/documents/{id}/rescan` | Reinspect against active rules |
| `POST /api/findings/{id}/action` | Accept, dismiss or record edited copy |
| `POST /api/documents/{id}/publish` | Sign-off/publication gate |
| `GET /api/documents/{id}/export?fmt=json\|csv` | Governance export |
| `GET/POST /api/rules`, `PATCH /api/rules/{id}` | Rule management |
| `GET /api/audit`, `GET /api/users`, `POST /api/users` | Audit and admin user management |

## Known limitations / production follow-up

- DOCX/PPTX pages are logical text chunks/slides; precise Word page layout is not available from `python-docx` alone.
- PDF contrast measurement assumes a white background; over-image/colored-background cases require visual verification. It is an automated estimate, not a full WCAG certification.
- Scanned PDF/image OCR requires the Tesseract system binary. OCR bounding boxes are approximate.
- Local embeddings use deterministic hashed-token vectors for reproducible offline ranking, not a semantic embedding model. PostgreSQL stores them in pgvector, but production retrieval quality should be evaluated with approved guideline corpora and a real embedding model before launch.
- Production SSO/MFA, password reset/invitations, tenant administration, object storage, malware scanning, rate limiting, retention/deletion policies, and formal security testing remain deployment hardening work.
- The benchmark target in the specification (greater than 90% precision/recall and zero hallucinated citations) must be measured on a labeled corpus; it is not claimed as achieved by this MVP.

## Write-time copy check and accessibility coverage

The Overview now includes a **Check the copy before it ships** tool. It sends up to 15,000 characters to the authenticated `POST /api/check-copy` endpoint, runs fast deterministic checks against the active workspace rules, and returns rule IDs, source guideline names, reasoning, and a suggested next step. It does not call the LLM for inline checks, so feedback is deterministic and avoids unexpected per-keystroke AI cost. It currently checks known patterns such as unsupported/quantified claims, approved product-name spelling, unapproved superlatives and visible pricing/promotional references.

Pricing detection is a **verification signal**, not proof that a price is outdated. The user/reviewer must compare the figure and campaign-validity window against an authoritative, current price book or campaign brief. The copy-check response explicitly explains this limitation.

For PPTX uploads, ContexA checks picture-shape alt-text metadata and flags absent or generic filename-only descriptions (for example `image.png`). It also performs the existing text contrast inspection for PDF spans. Logo cropping/clearspace and contrast over complex imagery still require visual confirmation against approved assets; generic text parsing does not reliably prove those visual conditions. Custom product names/aliases and policy rules can be managed in **Brand guidelines**.


## Motion and design preview

This build includes the Motion Study dashboard preview at `frontend/preview.html`. Start the frontend using `run-dev.bat`, then open `http://localhost:5173/preview.html` to view the animated glassmorphic dashboard design without signing in. This is a static visual preview using illustrative sample metrics; it is not connected to your backend data. The actual application UI is the default route at `http://localhost:5173`.

The motion pass includes a rotating faceted crystal, three intersecting orbital planes, moving CLAIMS/POLICY/ACCESS/PRICE controls, perspective depth ordering, staggered bento-card entrances, metric sparklines, sequenced activity bars, review-finding transitions, glass sheen on hover and focus-visible outlines. The 3D canvas reads the currently selected theme palette. Animations respect `prefers-reduced-motion`.

## UI visibility hotfix

The latest clean-minimal patch uses a solid `CA` brand monogram and persistent, high-contrast idle states for all primary/secondary/ghost/destructive and icon controls. Hover effects are limited to subtle lift/material changes; click feedback is a short compression motion rather than a glow. See `CLEAN_UI_VISIBILITY_FIX.md` for release notes.
