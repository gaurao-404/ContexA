# ContexA Enterprise Trust Foundation — Release Manifest

## What this release adds

This is an additive upgrade to the existing ContexA Trust OS. Existing Brand Truth Engine, Evidence Ledger, Truth Drift Radar, Trust Passport issuance/revocation, multimodal inspection, governed agents, Brand Digital Twin, Indic review, regulatory screening, incident management, policy simulation, audit, Cloudflare Worker, and the premium 16-theme frontend are retained.

### Identity

- Optional Supabase Auth password sign-in in `local`, `hybrid`, or `supabase` modes.
- FastAPI verifies asymmetric JWT signatures against the Supabase JWKS, issuer, audience, expiry and required identity claims.
- A verified Supabase identity links only to an already-provisioned ContexA user. Workspace and role remain sourced from ContexA's database record.
- The Supabase Custom Access Token Hook SQL derives `email_verified` from `auth.users.email_confirmed_at`; it is included in `infra/supabase/custom_access_token_hook.sql` because standard Supabase access tokens do not guarantee this claim.

### Evidence authenticity and cloud retention

- AWS KMS RSA-PSS detached signatures for canonical Trust Passport manifests and Merkle audit roots.
- KMS public key and signature material are returned with public Passport verification so third parties can independently verify the signed manifest.
- S3 archive writes verify the returned version ID and read back the actual Object Lock mode/retention date before reporting an object as immutable.
- Local filesystem archive is explicitly non-immutable; local HMAC is a development signer, not a public-key signature.
- Terraform under `infra/aws` provisions the KMS keys, private Object Lock S3 bucket, encryption, TLS-only bucket policy and least-privilege access for an existing ECS task role.

### Provenance and decision accountability

- Workspace-isolated Trust Graph built from existing ContexA documents, facts, sources, passports, drift events, incidents and agent runs.
- Stored agent decision traces record input/output hashes, evidence references, rules-engine/prompt version and human-approval boundary.
- Decision replay verifies stored trace integrity; it does not re-run a nondeterministic third-party model.
- Signed Merkle checkpoints anchor the existing audit event hashes. A verification endpoint validates the signed checkpoint.
- `ops/verify_passport_signature.py` verifies an exported AWS KMS Passport bundle offline, optionally checking the original asset SHA-256.

### Deployment support

- Cloudflare Pages deploy workflow with Supabase frontend build configuration.
- Existing Cloudflare Worker gateway and scheduled Truth Drift scanning retained.
- Render blueprint receives optional Supabase/AWS configuration fields. For AWS production without static cloud credentials, deploy the API on ECS/Fargate with the provisioned task role; the Terraform module does not provision a VPC/ECS cluster/ALB/ECR stack.

## Verification performed in this authoring environment

- Backend suite: **77 passed**, using a clean temporary SQLite database.
- Cloudflare Worker suite: **6 passed**; `node --check` passed.
- Python application modules: `compileall` passed.
- Frontend TypeScript/TSX parsing: **9 source files**, no syntax parse errors.
- Deployment YAML files (`render.yaml` and GitHub Actions workflows): parsed successfully.
- Offline Passport verifier: a generated RSA-PSS bundle and original asset passed end-to-end CLI verification.
- Vite production build: **not verified**. `npm install` timed out in this environment; this is not a frontend build pass.
- Terraform fmt/provider validation: **not run locally** because Terraform is not installed and external package download was unavailable. GitHub Actions includes formatting, init and validation steps.
- Live Supabase, AWS KMS, S3 Object Lock, Cloudflare Pages/Worker, SMTP, PostgreSQL FORCE RLS and public DNS: **not deployed or live-tested**; these require the operator's accounts, IAM roles, database and secrets.

## Required launch configuration

1. Apply the database migrations and verify 29 workspace-owned tables have forced RLS using the non-superuser, non-BYPASSRLS application database role.
2. Configure Supabase asymmetric signing keys, verified-email custom access token hook, MFA policy, issuer/JWKS URL and existing ContexA account provisioning.
3. Provision AWS KMS + S3 Object Lock with `infra/aws`; attach permissions to the actual ECS task role.
4. Configure `TRUST_SIGNING_PROVIDER=aws_kms`, `TRUST_KMS_KEY_ID`, archive bucket/retention/mode and `TRUST_ARCHIVE_REQUIRED=true` only after staging read-back tests pass.
5. Configure Cloudflare Pages/Worker, allowed origins, origin shared secret, cron token and public API URL.
6. Run Vite production build, live Postgres RLS tests, S3 retention/read-back, KMS signature verification, auth rejection tests, backup/restore and incident/approval end-to-end acceptance tests in staging.

## Important trust boundaries

A valid signature proves the manifest was signed and has not been altered since signing. A matching asset hash proves byte-level identity with that manifest. Neither proves that each marketing claim is factually true. Source authority, freshness, evidence quality and human/legal review remain separate decisions in ContexA.
