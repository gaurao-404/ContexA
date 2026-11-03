resource "aws_kms_key" "trust_signing" {
  description              = "ContexA Trust Passport and Merkle anchor asymmetric signing key"
  customer_master_key_spec = "RSA_2048"
  key_usage                = "SIGN_VERIFY"
  deletion_window_in_days  = 30
  enable_key_rotation      = false

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      {
        Sid       = "EnableAccountRootAdministration"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "AllowContexATaskSigningAndPublicVerification"
        Effect    = "Allow"
        Principal = { AWS = "${data.aws_iam_role.contexa_task.arn}" }
        Action    = ["kms:Sign", "kms:Verify", "kms:GetPublicKey", "kms:DescribeKey"]
        Resource  = "*"
      }
    ], [for i, arn in var.kms_key_administrator_arns : {
      Sid       = "KeyAdministrator${i}"
      Effect    = "Allow"
      Principal = { AWS = arn }
      Action    = ["kms:DescribeKey", "kms:GetKeyPolicy", "kms:PutKeyPolicy", "kms:EnableKey", "kms:DisableKey", "kms:ScheduleKeyDeletion", "kms:CancelKeyDeletion", "kms:TagResource", "kms:UntagResource"]
      Resource  = "*"
    }])
  })

  tags = { Application = "ContexA", Purpose = "TrustSigning" }
}

resource "aws_kms_key" "evidence_encryption" {
  description             = "ContexA S3 evidence archive encryption key"
  key_usage               = "ENCRYPT_DECRYPT"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnableAccountRootAdministration"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "AllowContexATaskArchiveEncryption"
        Effect    = "Allow"
        Principal = { AWS = "${data.aws_iam_role.contexa_task.arn}" }
        Action    = ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:DescribeKey"]
        Resource  = "*"
      }
    ]
  })

  tags = { Application = "ContexA", Purpose = "EvidenceArchiveEncryption" }
}

resource "aws_s3_bucket" "evidence" {
  bucket              = var.evidence_bucket_name
  object_lock_enabled = true
  force_destroy       = false

  tags = { Application = "ContexA", Purpose = "ImmutableEvidenceArchive" }
}

resource "aws_s3_bucket_versioning" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_object_lock_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  rule {
    default_retention {
      mode = var.object_lock_mode
      days = var.retention_days
    }
  }
  depends_on = [aws_s3_bucket_versioning.evidence]
}

resource "aws_s3_bucket_server_side_encryption_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.evidence_encryption.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "evidence" {
  bucket                  = aws_s3_bucket.evidence.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "evidence_tls_only" {
  bucket = aws_s3_bucket.evidence.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.evidence.arn, "${aws_s3_bucket.evidence.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

resource "aws_iam_policy" "contexa_evidence_access" {
  name        = "ContexA-EvidenceVault-${substr(aws_s3_bucket.evidence.id, 0, 24)}"
  description = "Least-privilege access for the ContexA ECS task to sign passports and archive evidence."
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "SignAndVerifyTrustManifests"
        Effect   = "Allow"
        Action   = ["kms:Sign", "kms:Verify", "kms:GetPublicKey", "kms:DescribeKey"]
        Resource = aws_kms_key.trust_signing.arn
      },
      {
        Sid      = "ArchiveEvidenceObjects"
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject", "s3:GetObjectVersion", "s3:GetObjectRetention", "s3:PutObjectRetention"]
        Resource = "${aws_s3_bucket.evidence.arn}/*"
      },
      {
        Sid      = "InspectEvidenceVaultConfiguration"
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation", "s3:GetBucketObjectLockConfiguration"]
        Resource = aws_s3_bucket.evidence.arn
      },
      {
        Sid      = "EncryptEvidenceArchiveObjects"
        Effect   = "Allow"
        Action   = ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:DescribeKey"]
        Resource = aws_kms_key.evidence_encryption.arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "contexa_task" {
  role       = var.ecs_task_role_name
  policy_arn = aws_iam_policy.contexa_evidence_access.arn
}
