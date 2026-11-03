# ContexA Studio — 5-minute hackathon judge runbook

## One-line pitch

**ContexA is a pre-publication brand integrity control plane:** it checks content against approved brand facts and policies, routes risk to the right reviewer, and preserves verifiable evidence and decisions before anything goes live.

## The problem / why now

Teams publish across campaigns, formats and channels faster than legal and brand teams can manually verify every claim. Guidelines become stale PDFs, product facts are scattered, and a final approval often leaves no defensible record of which evidence supported the decision. ContexA puts policy, evidence, review and audit into one workspace.

## 5-minute live demo sequence

| Time | What to show | Judge takeaway |
|---|---|---|
| 0:00–0:30 | Sign in as Brand Admin (`admin@contexa.local`) or a dedicated demo account. Show the 16 themes and the role-aware workspace shell. | This is a functioning product, not a slide-only concept. |
| 0:30–1:15 | If the workspace is empty, click **Prepare demo workspace** on the dashboard to seed the deterministic synthetic examples. Then use **Check this copy** with a deliberately risky claim, e.g. “The world's safest, clinically proven, 100% guaranteed solution.” | The judge sees a populated, repeatable workspace and fast deterministic checks flag unsupported superlatives/quantified claims with the applicable rule. |
| 1:15–2:00 | Upload a synthetic PDF/DOCX with an unsupported product claim; open the finding and its source context. | The review is grounded in the submitted document, not a generic chatbot response. |
| 2:00–2:45 | Open Insights → Brand Intelligence / approved facts / Evidence Ledger. Show a fact with supporting quote and source, then inspect citation verification. | Approved truth is a governed asset, and claims can be traced to evidence. |
| 2:45–3:30 | Simulate a policy change, inspect the version history / risk review routing, then run the seeded evaluation benchmark. | Policy change impact can be tested before rollout; high-risk decisions can be routed. |
| 3:30–4:15 | Open Audit and verify the chain; show review decision, actor, timestamp and evidence provenance. | Governance decisions are accountable and exportable. |
| 4:15–5:00 | Open Settings → Cloudflare control plane. Explain Pages, Worker, origin lock, R2, Turnstile and optional AI Gateway; show statuses honestly. | The deployment path scales beyond a laptop demo without claiming cloud services are already provisioned. |

## Demo accounts

The UI contains role-selectable seeded identities for the local submission/demo mode. Use them only with synthetic data and only when the deployed demo has been explicitly configured to permit those accounts. Never leave seeded credentials enabled on a public customer deployment. For a live public demo, create separate judge accounts and set a short-lived demo data reset plan.

## Demo content to prepare

For the fastest first run, use the dashboard's **Prepare demo workspace** action when it is available (typically when the workspace has no documents). It seeds three deterministic synthetic documents—`DEMO_Q4_Launch_Campaign.txt`, `DEMO_Product_Naming_Review.txt` and `DEMO_Pricing_Refresh.txt`—and is safe to re-run. Then use **Quick Copy Check** for the live risky-claim moment. If you prefer a richer upload demonstration, use synthetic company/product names and no confidential customer material. Prepare:

- One brand guideline file with a clear prohibited phrase, approved terminology and a claims rule.
- One approved product fact with a short exact source quotation and source document.
- One intentionally risky one-page marketing PDF/DOCX with a superlative, a quantified claim and an out-of-date price reference.
- One safe control example that should pass, so the demo shows precision as well as flagging.

Use the app's own seeded benchmark/evaluation suite for repeatable performance claims. Clearly label seeded results as internal synthetic test cases—not an independent accuracy certification or production outcome.

## Suggested judge narrative

1. **Not another copywriting assistant:** ContexA is an operational policy/evidence/review system. AI is optional; deterministic checks still run offline.
2. **Trust is traceable:** findings carry rule IDs and source context; approved facts link to evidence; reviewers record explicit decisions.
3. **Risk changes the workflow:** severity and permissions influence who needs to review and whether publication can proceed.
4. **The platform is deployable:** React can live on Cloudflare Pages, a narrow Worker protects the API edge, FastAPI runs on a Python host, PostgreSQL enforces tenant isolation, and private R2 stores uploads.
5. **Honest boundaries:** visual logo/clearspace checks, live fact synchronization, actual email delivery, malware scanning and real-world benchmark accuracy require external services/data and human validation. Do not imply those are universally solved.

## Hackathon scoring checklist

- [ ] App opens in a clean browser and judge credentials are available.
- [ ] A complete sign-in, review, approve/reject and audit flow works without any external AI key.
- [ ] API health and frontend production build are verified.
- [ ] At least one seeded benchmark can be run in front of judges.
- [ ] All sample documents and facts are synthetic and the source quotations are real within those files.
- [ ] Cloudflare status labels accurately show what is configured versus optional/not set.
- [ ] A short recorded fallback demo is available in case venue internet fails.
- [ ] Pitch deck and QR code point to the actual deployed HTTPS URL; do not print a placeholder link.

## 30-second closing

“ContexA turns brand governance from a scattered checklist into a release control plane. Every risky claim is checked against explicit policy and approved truth; every decision is routed, evidenced and auditable. It works deterministically offline, and can be deployed with Cloudflare at the edge when the organization is ready.”

## Trust OS showcase — add this after the core governance demo

Use a synthetic company named **AstraTech** and test data only. The eight capabilities are integrated in the **Trust OS** navigation item. To keep the demo authentic, use an actual test URL that your team controls for source monitoring; do not fabricate a drift event or present a seeded legal keyword as legal compliance.

| Feature | Judge action | Evidence to show | Boundary to say aloud |
|---|---|---|---|
| Truth Drift Radar | Register a public HTTPS test source, scan it, change the source content at the controlled origin, and scan again. | Snapshot hash change, affected fact/event, linked incident and resolution. | A content change is a drift signal, not automatic proof that a claim is false. |
| Trust Passport | Issue only for a publish-ready synthetic asset with no critical open finding; open the QR verification route, then revoke it. | File SHA-256, signed attestation, status, issue/revoke state. | The passport attests to recorded provenance/integrity and approval metadata; it does not certify truth on its own. |
| Multimodal | Upload a synthetic image/PDF; optionally a short video if FFmpeg is present. Supply a transcript for an audio example. | Extracted text/frames, detected indicators, saved inspection record. | Audio transcription must be supplied; video sampling is bounded; detections require review. |
| Governance agents | Run the review workflow against a synthetic document. | Persisted agent steps, risk/evidence findings, created review task. | Agents can triage and recommend, not approve or publish. |
| Brand Digital Twin | Propose a warranty/price/product fact change. | Saved scenario and potentially affected stored documents. | A simulation is non-destructive and can miss paraphrased/external campaign copies. |
| Indic intelligence | Compare the approved English sentence with a Marathi/Hindi localization that intentionally changes a number or removes a disclosure. | Unicode numeral/disclosure mismatch indicators and saved review. | This is a deterministic parity aid, not complete translation or cultural validation; use a native reviewer. |
| Regulatory intelligence | Assess synthetic influencer/AI-generated content against enabled requirements. | Trigger matches, missing indicators, authority/source URL and saved assessment. | Seeded requirements are reference summaries; keyword screening is not legal advice or compliance certification. |
| Incident centre | Open an incident from a drift event or create one manually; acknowledge, investigate and resolve it. | Severity, related assets/source, owner/status notes and resolution. | This is a tracked response workflow; it does not automatically remove external content. |

### Preconditions for the Trust Passport judge scan

The backend must have `TRUST_PASSPORT_SIGNING_KEY` set to a stable random secret, `PUBLIC_APP_URL` set to the deployed HTTPS frontend, and a document that has passed the application's publish-readiness gate. The judge's browser must be able to reach the deployed `/verify/<id>` route and the public verification API. Do not use a localhost QR for a remote judge.

### What not to claim

- Do not call the current seeded regulatory rules a live legal database.
- Do not call OCR or visual text extraction a deepfake detector.
- Do not call a change in an external page an automatically verified falsehood.
- Do not claim all Indic-language semantics are understood; the implemented checker is deterministic and bounded.
- Do not describe scheduled monitoring, SMTP, R2, ClamAV, PostgreSQL RLS or Cloudflare as live until the deployed environment has passed its acceptance test.
