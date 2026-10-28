# ContexA Studio — Submission Quick Start

## No Ollama or paid API key required

Use **Submission Mode** for your evaluation/demo computer. It forces deterministic rules-only checks even if an existing `.env` file contains AI settings.

### Windows

1. Extract the project ZIP.
2. Double-click `run-submission.bat`.
3. On the first run, let it install Python and npm dependencies. This first installation requires a network connection; later launches reuse the local environments.
4. Open `http://localhost:5173` when Vite starts.
5. Sign in with `admin@contexa.local` / `ContexA!2026`.
6. If the workspace is empty, click **Prepare demo workspace**. It adds three clearly labelled example documents and generated findings using the same deterministic rules engine, without calling an AI model.

The topbar shows **SUBMISSION MODE · RULES ONLY**. Copy checks, document parsing, rule-based findings, reviewer actions, audit trail, exports and publication gates do not need Ollama.

### Stop the app

Close the API terminal and the frontend terminal. The app is local; it is not publicly hosted.

### Optional AI during development

When you do want local contextual review, use `run-dev.bat` and configure `OLLAMA_ENABLED=true` plus `AI_VERIFICATION_ENABLED=true` in `.env`. The submission launcher always forces AI off for that run.

### Demo credentials

- Brand Admin: `admin@contexa.local` / `ContexA!2026`
- Manager: `manager@contexa.local` / `Manager!2026`
- SME / Legal: `legal@contexa.local` / `Legal!2026`
- Creator: `creator@contexa.local` / `Creator!2026`

These are local demo credentials, not production credentials.

## Visual preview

After launching the frontend, open `http://localhost:5173/palette-motion-lab.html` for the interactive visual lab with sixteen palette choices, the 3D entrance animation and Calm / Studio / Cinematic motion profiles. Use **Replay entrance** to view the sign-in handoff animation. Click navigation entries to inspect tab transitions and palette cards to test animated color changes. Its sample metrics are illustrative; the authenticated application at `/` uses backend data.
