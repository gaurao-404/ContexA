# ContexA AWS Evidence Vault

This Terraform module provisions the **AWS trust-signing and evidence-archive boundary** used by ContexA. It is intentionally additive: it does not replace the existing Cloudflare Pages/Workers/R2 edge and app-asset path, nor does it create a second application database.

## Resources

- Asymmetric RSA-2048 KMS key (`SIGN_VERIFY`) for Trust Passport and audit Merkle signatures.
- Customer-managed symmetric KMS key for S3 server-side encryption.
- Private S3 bucket with Object Lock enabled, versioning, default retention, SSE-KMS, public-access blocks, and a TLS-only bucket policy.
- Least-privilege IAM policy attached to an **existing ECS task role**. The role is used by the FastAPI workload; no static AWS access keys are issued.

## Before applying

1. Create the ECS task role in your existing ECS deployment (or use the role your deployment module creates). It must exist before this module is applied because the KMS key policy names it.
2. Choose an evidence bucket name that is globally unique.
3. Consult your records-retention/legal team before choosing Object Lock mode and retention. `GOVERNANCE` is the safer default for initial rollout; `COMPLIANCE` can prevent even account administrators from shortening retention.
4. Have an AWS break-glass administrator role ready. Keep key administration separate from the routine application task role.
5. Run Terraform using an operator identity that can create KMS keys, S3 buckets, IAM policies/attachments and read the named ECS role.

## Apply

```bash
cd infra/aws
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with the real, unique bucket and existing ECS task role.
terraform init
terraform fmt -check
terraform validate
terraform plan -out contexa-evidence.plan
terraform apply contexa-evidence.plan
terraform output contexa_api_environment
```

Review the plan before applying. Do not commit `terraform.tfvars`, state files, plan files, or cloud credentials. Use a remote, encrypted, access-controlled Terraform state backend for team/production use; configure that backend in your deployment repository rather than this reusable module.

## FastAPI environment

Map the `contexa_api_environment` output to the backend task environment:

```dotenv
AWS_REGION=ap-south-1
TRUST_SIGNING_PROVIDER=aws_kms
TRUST_KMS_KEY_ID=arn:aws:kms:ap-south-1:123456789012:key/REPLACE
TRUST_KMS_SIGNING_ALGORITHM=RSASSA_PSS_SHA_256
EVIDENCE_ARCHIVE_BUCKET=replace-with-bucket
EVIDENCE_ARCHIVE_PREFIX=contexa
EVIDENCE_ARCHIVE_RETENTION_DAYS=365
EVIDENCE_ARCHIVE_MODE=GOVERNANCE
EVIDENCE_ARCHIVE_SSE=aws:kms
EVIDENCE_ARCHIVE_KMS_KEY_ID=arn:aws:kms:ap-south-1:123456789012:key/REPLACE
TRUST_ARCHIVE_REQUIRED=true
```

The ECS **task role**, not the task execution role, must be associated with the running API container. Verify with `aws sts get-caller-identity` from the workload environment and test a passport issuance in a non-production bucket first. The app uses the AWS SDK default credential provider chain; it does not require `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` when running with an ECS task role.

## Verification and operational controls

- A Passport is only issued after the existing application approval gate passes.
- The app signs a canonical JSON manifest with KMS and stores the signature plus public key material in the public verification index.
- The same signed manifest is written to S3. When Object Lock is configured, S3 applies retention to that object version.
- The app reports `local_filesystem` as **not immutable**. Do not describe local mode as WORM storage.
- Verify `GetObjectRetention` and the returned `VersionId` for test objects. Periodically run a restore/read-back drill and compare SHA-256 values.
- CloudTrail should be enabled at the AWS account/organization level to record KMS and S3 control-plane activity. CloudWatch alarms should cover KMS failures, archive write failures, API error rates and unusual access.
- Keep KMS key administration separate from app task permissions. Do not grant `kms:PutKeyPolicy` or `kms:ScheduleKeyDeletion` to the app role.
- Object Lock does not prove that the underlying marketing claim is true. It preserves the evidence package and retention state; factual verification remains the responsibility of ContexA's source/evidence workflow and authorized reviewers.

## Limitations

This module provisions the evidence vault and attaches the required permissions to an existing ECS task role. It does **not** provision the complete ECS service, ALB, VPC, ECR repository, DNS, Supabase project, Cloudflare account or secrets manager. Those are environment-specific foundations. Use your organization's approved network and deployment baseline before exposing the API publicly.
