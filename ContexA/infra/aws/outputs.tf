output "evidence_bucket_name" { value = aws_s3_bucket.evidence.id }
output "evidence_bucket_arn" { value = aws_s3_bucket.evidence.arn }
output "trust_signing_kms_key_arn" { value = aws_kms_key.trust_signing.arn }
output "evidence_encryption_kms_key_arn" { value = aws_kms_key.evidence_encryption.arn }
output "contexa_api_environment" {
  value = {
    AWS_REGION                         = var.aws_region
    TRUST_SIGNING_PROVIDER             = "aws_kms"
    TRUST_KMS_KEY_ID                   = aws_kms_key.trust_signing.arn
    TRUST_KMS_SIGNING_ALGORITHM        = "RSASSA_PSS_SHA_256"
    EVIDENCE_ARCHIVE_BUCKET            = aws_s3_bucket.evidence.id
    EVIDENCE_ARCHIVE_RETENTION_DAYS    = tostring(var.retention_days)
    EVIDENCE_ARCHIVE_MODE              = var.object_lock_mode
    EVIDENCE_ARCHIVE_SSE               = "aws:kms"
    EVIDENCE_ARCHIVE_KMS_KEY_ID        = aws_kms_key.evidence_encryption.arn
    TRUST_ARCHIVE_REQUIRED             = "true"
  }
  sensitive = false
}
