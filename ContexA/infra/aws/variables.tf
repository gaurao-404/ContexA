variable "aws_region" {
  description = "AWS region for the ContexA evidence vault."
  type        = string
  default     = "ap-south-1"
}

variable "evidence_bucket_name" {
  description = "Globally unique S3 bucket name for signed ContexA evidence manifests."
  type        = string
}

variable "retention_days" {
  description = "Default S3 Object Lock retention period. Choose this with legal/compliance counsel."
  type        = number
  default     = 365
  validation {
    condition     = var.retention_days >= 1 && floor(var.retention_days) == var.retention_days
    error_message = "retention_days must be a positive whole number."
  }
}

variable "object_lock_mode" {
  description = "GOVERNANCE allows authorized bypass; COMPLIANCE is much stricter and cannot be shortened by account administrators."
  type        = string
  default     = "GOVERNANCE"
  validation {
    condition     = contains(["GOVERNANCE", "COMPLIANCE"], var.object_lock_mode)
    error_message = "object_lock_mode must be GOVERNANCE or COMPLIANCE."
  }
}

variable "ecs_task_role_name" {
  description = "Existing ECS task role used by the ContexA API task. IAM permissions are attached to this role."
  type        = string
}

variable "kms_key_administrator_arns" {
  description = "IAM role/user ARNs allowed to administer the KMS keys. Use break-glass role ARNs, not application principals."
  type        = list(string)
  default     = []
}
