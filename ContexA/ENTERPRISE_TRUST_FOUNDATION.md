# ContexA Enterprise Trust Foundation

This release adds an enterprise foundation layer to the existing ContexA Trust OS while preserving the existing Brand Truth Engine, Evidence Ledger, policy simulation, drift monitoring, multimodal inspection, governance agents, regulatory screening, incident management, Trust Passports and Cloudflare edge gateway.

## New foundation services

### Identity federation

Supabase Auth can be enabled as an external OIDC/JWKS-backed identity provider. FastAPI validates issuer, audience, signature, expiry and a verified-email claim, then links to an existing ContexA user. Because the standard Supabase access-token claim set does not guarantee `email_verified`, apply and enable the supplied Custom Access Token Hook; it derives the claim from `auth.users.email_confirmed_at`. Authorization continues to come from ContexA's canonical workspace membership. See `infra/supabase/README.md`.

### KMS-backed authenticity

When `TRUST_SIGNING_PROVIDER=aws_kms`, ContexA signs canonical Passport manifests and Merkle audit roots using an asymmetric AWS KMS key. The Passport signature index retains the detached signature and public-key material needed for offline verification. The public QR endpoint returns the canonical signed manifest plus the signature bundle, so a third party can independently verify the RSA-PSS signature against the included public key and manifest digest. Local HMAC remains available for development; it must not be marketed as externally verifiable public-key signing.

### Evidence archive

When an S3 bucket is configured, the exact signed Passport manifest is archived to S3. Configure S3 Object Lock and SSE-KMS for retention-grade preservation. The local filesystem adapter is explicitly marked non-immutable. See `infra/aws/README.md`.

### Trust Graph

`/api/foundation/graph` exposes workspace-scoped nodes and edges. `POST /api/foundation/graph/rebuild` rebuilds graph records from existing ContexA objects, including documents, approved facts, monitored sources, passports, drift events, incidents and agent runs. The graph is an index/relationship layer; the original business objects remain canonical.

### Decision Replay

Agent runs create decision trace records with input/output hashes, evidence references, model/engine identifier, prompt/rules version and integrity hash. `/api/foundation/decision-traces/{id}/replay` checks the persisted trace for tampering. It intentionally does not rerun an external model or claim that a recorded model conclusion was correct.

### Audit Merkle anchors

Authorized Brand Admins can create signed Merkle checkpoints over existing audit event hashes. An anchor is a cryptographic checkpoint over the selected event set; it does not replace the source audit events, database backups, CloudTrail or independent retention controls.

## Readiness and truthful status

- Local HMAC signing: development only; not public-key verification.
- AWS KMS signing: production-grade signer when the AWS key, IAM permissions, and deployment identity are configured and tested.
- Local archive: integrity checked but not immutable.
- S3 Object Lock archive: retention-grade only when the bucket has Object Lock enabled, versioning and default/object retention are verified, and the API workload role has least-privilege permissions.
- Supabase Auth: federated login and token validation; no automatic account/workspace provisioning, SAML/SCIM provisioning, or passkeys in this release.
- Trust Graph: reflects known ContexA records. It is not a web-scale knowledge graph or external source crawler.
- Decision Replay: integrity verification of stored traces, not deterministic reproduction of nondeterministic third-party model runs.

## Production release gates

1. Provision PostgreSQL and apply all additive ContexA migrations.
2. Verify RLS as a non-owner application role using simultaneous sessions from at least two workspaces.
3. Configure Supabase Auth and test token verification/linking with verified and unverified test users.
4. Provision AWS resources with Terraform under `infra/aws` and attach the policy to the actual ECS task role.
5. Issue a test Passport, verify its signature independently, confirm S3 `VersionId` and Object Lock retention, and test read-back SHA-256.
6. Test KMS key rotation strategy, break-glass access, backup/restore and evidence retention procedures.
7. Deploy the backend behind the existing Cloudflare Worker; keep the origin shared-secret protection enabled.
8. Run the backend, frontend production, Worker and infrastructure CI checks against production-equivalent configuration.
