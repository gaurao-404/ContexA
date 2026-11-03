# Login fix

**Problem:** `.env.example` shipped with `AUTH_MODE=supabase` (and `frontend/.env.example` with `VITE_AUTH_MODE=supabase`).
The run scripts copy it to `.env`, so the API rejected every email/password login with
"Local password authentication is disabled...".

**Fix:**
- `.env.example` -> `AUTH_MODE=local`, `SUPABASE_SESSION_CHECK_REQUIRED=false`
- `frontend/.env.example` -> `VITE_AUTH_MODE=local`
- `run-dev.*` / `run-submission.*` now also create `frontend/.env`
- Fixed two TypeScript errors that made `npm run build` fail (App.tsx, TrustOSPage.tsx)

A ready-to-use `.env` and `frontend/.env` are included. If you already have your own `.env`, set `AUTH_MODE=local` in it.

**Login:** admin@contexa.local / ContexA!2026 (also manager@, creator@, legal@contexa.local)
**Forgot password:** works locally; the reset link is shown on screen (and in the API log) because SMTP isn't configured.
**Back to Supabase later:** set AUTH_MODE=supabase and VITE_AUTH_MODE=supabase, fill real SUPABASE_* values.

---

# Round 4 additions (backend + database)

- New tables: `notifications`, `comments`, `compliance_snapshots` (+ 7 composite indexes, migration `2026_11_01_04`, RLS policies)
- New API: notifications inbox, threaded comments with @mentions, per-document activity, compliance trend (JSON/CSV), reviewer workload, server-side search, `/api/health/live|ready`, `/api/metrics`
- Request-ID + JSON access logging middleware
- `ops/backup_sqlite.py`, `ops/round4_collaboration_postgres.sql`
- New `README.md` with architecture / auth / review-lifecycle flowcharts and an ER diagram (old README -> `docs/README_LEGACY.md`)
- 5 new test modules' worth of coverage in `backend/tests/test_round4_collaboration.py` (96 tests total)
- The UI is unchanged; typed client methods for the new endpoints are in `frontend/src/api.ts`

---

# Round 5: UI + sign-in
- Demo accounts (email + password) are shown on the sign-in page, click-to-fill, admin pre-filled. Shown only when the server is in development/demo/test mode.
- Sign-in page now asks `/api/auth/config`; *Forgot password?* / *Create account* / demo panel are hidden when they cannot work (e.g. production without SMTP).
- The topbar bell was a toast-only placeholder; it is now a real notification inbox.
- New UI: Discussion + Activity on the review page, Compliance trend on the dashboard (same neubrutalism styling).
- Fixed: notification click now opens the document immediately.

---

# Round 6: interface styles
- New **style switcher** (sign-in page + Settings): *Professional* (default, document-first "ledger" look) and *Neubrutalism* (original, now scoped so it can be turned off). Saved in the browser.
- Professional: warm paper + ink palette, serif headings, mono only for rule codes, dark sidebar, signal colour reserved for risk, no 3D hero / splash animation, status sentence from real data on the dashboard, annotated example on sign-in.
- Review page now **highlights flagged passages in the document text** by severity.
- Fixed pre-existing contrast bugs in the Neubrutalism layer (unreadable login strip, dark "Open" filter tab).
- Verified with real screenshots (headless Chromium) and an automated contrast audit: 0 low-contrast items in both styles.

# Round 7: removed fake data from the dashboard
- The four stat cards drew hard-coded sparklines (the same upward shapes regardless of data) and a static "Live" label. They now draw only from real stored daily snapshots, show nothing when fewer than two exist, and the integrity card shows the real change (e.g. "-36 pts").
- "Documents in review" has no history line because snapshots don't store that figure.
