# ContexA Round 3 — 6-minute Demo Script

Use a dedicated demo workspace and fictional product/pricing data. All sample numbers are illustrative.

## 1. Establish a source of truth (60–75 seconds)
1. Sign in as Brand Admin and upload a fictional approved product price book.
2. Open Insights → Brand Intelligence Lab and create a price fact.
3. Select the uploaded price book, paste the exact supporting quotation, and save.
4. Show the source verification result and approve the draft fact.

## 2. Catch an outdated value with evidence (60 seconds)
1. Upload campaign copy containing an older price.
2. Open its finding and show the canonical approved value versus the detected value.
3. Open the Evidence Ledger and explain the linked fact, source quote, page locator and scan record.
4. Explain that a missing approved source is marked unverifiable rather than guessed to be false.

## 3. Simulate a policy change (60 seconds)
1. Select an active terminology rule and propose a stricter pattern.
2. Run the historical-document simulation and inspect affected documents/sample excerpts.
3. Explain that this simulation does not change active policy.
4. Add a meaningful change note, apply the simulation and show the new rule version.

## 4. Demonstrate review routing and assets (45 seconds)
1. Open Review Tasks and show a high-risk claim routed to SME / Legal or pricing/asset finding routed to Manager.
2. Open the Brand Asset Registry; upload a logo or template as a draft, approve it, and show workspace ownership and SHA-256 identity.

## 5. Prove quality and audit traceability (60–75 seconds)
1. Run the 50-case deterministic seeded benchmark.
2. Show precision, recall, F1 and run history; state that this measures only the seeded dataset.
3. Open Audit and click **Verify integrity** to validate the SHA-256 event chain.
4. Show workspace export; explain that password hashes and private storage paths are not included.

## 6. Account/privacy controls (30–45 seconds)
1. Show registration and email verification settings, or the one-time invitation flow.
2. Explain that deleting a workspace requires a Brand Admin password and exact workspace-name confirmation.
3. Explain that production signup requires SMTP verification, PostgreSQL and private durable storage configuration.

## Close
ContexA connects approved brand facts and assets to content checks, preserves source evidence, lets admins simulate policy changes before activation, routes risky findings to people, measures quality on reproducible test cases, and provides workspace-level audit and data controls.

**Honest disclosure:** demo metrics are illustrative/seeded; do not present synthetic evaluation scores as real-world detection accuracy.
