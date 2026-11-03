"""Optional cloud trust providers for ContexA.

Local providers are suitable for development/test only. AWS KMS and S3 Object Lock
are used when configured; the API reports provider readiness and never labels a
local filesystem archive as immutable.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import (
    AWS_REGION, EVIDENCE_ARCHIVE_BUCKET, EVIDENCE_ARCHIVE_PREFIX,
    EVIDENCE_ARCHIVE_RETENTION_DAYS, EVIDENCE_ARCHIVE_MODE,
    EVIDENCE_ARCHIVE_SSE, EVIDENCE_ARCHIVE_KMS_KEY_ID,
    TRUST_SIGNING_PROVIDER, TRUST_KMS_KEY_ID, TRUST_KMS_SIGNING_ALGORITHM,
    TRUST_PASSPORT_SIGNING_KEY, STORAGE_DIR,
)


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


@dataclass(frozen=True)
class SignatureResult:
    provider: str
    key_id: str
    algorithm: str
    signature_b64: str
    public_key_b64: str | None
    manifest_sha256: str


def _aws_client(service: str):
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - dependency checked in deploy
        raise RuntimeError("AWS integration requires boto3. Install backend requirements.") from exc
    return boto3.client(service, region_name=AWS_REGION or None)


def sign_manifest(payload: dict[str, Any]) -> SignatureResult:
    """Sign canonical manifest bytes with local HMAC or AWS KMS asymmetric key."""
    body = canonical_json(payload)
    digest = hashlib.sha256(body).digest()
    digest_hex = digest.hex()
    if TRUST_SIGNING_PROVIDER == "aws_kms":
        if not TRUST_KMS_KEY_ID:
            raise RuntimeError("TRUST_KMS_KEY_ID is required when TRUST_SIGNING_PROVIDER=aws_kms.")
        kms = _aws_client("kms")
        result = kms.sign(
            KeyId=TRUST_KMS_KEY_ID,
            Message=digest,
            MessageType="DIGEST",
            SigningAlgorithm=TRUST_KMS_SIGNING_ALGORITHM,
        )
        public = kms.get_public_key(KeyId=result["KeyId"])
        return SignatureResult(
            provider="aws_kms", key_id=result["KeyId"],
            algorithm=result["SigningAlgorithm"],
            signature_b64=base64.b64encode(result["Signature"]).decode("ascii"),
            public_key_b64=base64.b64encode(public["PublicKey"]).decode("ascii"),
            manifest_sha256=digest_hex,
        )
    signature = hmac.new(TRUST_PASSPORT_SIGNING_KEY.encode("utf-8"), body, hashlib.sha256).digest()
    return SignatureResult(
        provider="local_hmac", key_id="contexa-local-hmac-v1",
        algorithm="HMAC-SHA256", signature_b64=base64.b64encode(signature).decode("ascii"),
        public_key_b64=None, manifest_sha256=digest_hex,
    )


def verify_manifest(payload: dict[str, Any], signature: SignatureResult | dict[str, Any]) -> bool:
    """Verify a signed manifest. AWS verification uses KMS Verify, not key export assumptions."""
    fields = signature if isinstance(signature, dict) else signature.__dict__
    body = canonical_json(payload)
    digest = hashlib.sha256(body).digest()
    if not hmac.compare_digest(hashlib.sha256(body).hexdigest(), str(fields.get("manifest_sha256", ""))):
        return False
    try:
        raw_signature = base64.b64decode(fields["signature_b64"], validate=True)
        if fields.get("provider") == "aws_kms":
            # KMS returns the DER-encoded public key for asymmetric signing keys.
            # Verify locally when that public key is part of the public attestation,
            # so a passport QR can be checked without calling the issuer's AWS account.
            public_key_b64 = fields.get("public_key_b64")
            if public_key_b64:
                from cryptography.hazmat.primitives import hashes, serialization
                from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa, utils
                public_key = serialization.load_der_public_key(base64.b64decode(public_key_b64, validate=True))
                algorithm = str(fields.get("algorithm", ""))
                prehashed = utils.Prehashed(hashes.SHA256())
                if isinstance(public_key, rsa.RSAPublicKey) and algorithm == "RSASSA_PSS_SHA_256":
                    public_key.verify(raw_signature, digest,
                        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256().digest_size), prehashed)
                    return True
                if isinstance(public_key, rsa.RSAPublicKey) and algorithm == "RSASSA_PKCS1_V1_5_SHA_256":
                    public_key.verify(raw_signature, digest, padding.PKCS1v15(), prehashed)
                    return True
                if isinstance(public_key, ec.EllipticCurvePublicKey) and algorithm == "ECDSA_SHA_256":
                    public_key.verify(raw_signature, digest, ec.ECDSA(prehashed))
                    return True
                return False
            result = _aws_client("kms").verify(
                KeyId=fields["key_id"], Message=digest, MessageType="DIGEST",
                Signature=raw_signature, SigningAlgorithm=fields["algorithm"],
            )
            return bool(result.get("SignatureValid"))
        expected = hmac.new(TRUST_PASSPORT_SIGNING_KEY.encode("utf-8"), body, hashlib.sha256).digest()
        return hmac.compare_digest(raw_signature, expected)
    except Exception:
        return False


def archive_evidence(payload: bytes, object_key: str, content_type: str = "application/json") -> dict[str, Any]:
    """Archive a signed evidence manifest. Local mode is explicitly non-immutable."""
    digest = hashlib.sha256(payload).hexdigest()
    if EVIDENCE_ARCHIVE_BUCKET:
        prefix = EVIDENCE_ARCHIVE_PREFIX.strip("/")
        key = f"{prefix}/{object_key}".strip("/") if prefix else object_key
        args: dict[str, Any] = {
            "Bucket": EVIDENCE_ARCHIVE_BUCKET, "Key": key, "Body": payload,
            "ContentType": content_type, "Metadata": {"sha256": digest, "system": "contexa"},
        }
        if EVIDENCE_ARCHIVE_SSE:
            args["ServerSideEncryption"] = EVIDENCE_ARCHIVE_SSE
        if EVIDENCE_ARCHIVE_SSE == "aws:kms" and EVIDENCE_ARCHIVE_KMS_KEY_ID:
            args["SSEKMSKeyId"] = EVIDENCE_ARCHIVE_KMS_KEY_ID
        retained_until = None
        lock_mode = None
        if EVIDENCE_ARCHIVE_RETENTION_DAYS > 0:
            retained_until = datetime.now(timezone.utc) + timedelta(days=EVIDENCE_ARCHIVE_RETENTION_DAYS)
            lock_mode = EVIDENCE_ARCHIVE_MODE
            args["ObjectLockMode"] = lock_mode
            args["ObjectLockRetainUntilDate"] = retained_until
        s3 = _aws_client("s3")
        response = s3.put_object(**args)
        version_id = response.get("VersionId")
        immutable = False
        verified_retain_until = None
        if lock_mode:
            if not version_id:
                raise RuntimeError("S3 did not return a version ID for the Object Lock evidence write.")
            # Confirm the retention that S3 actually stored rather than marking the
            # record immutable solely because a retention request was sent.
            actual = s3.get_object_retention(Bucket=EVIDENCE_ARCHIVE_BUCKET, Key=key, VersionId=version_id)
            retention = actual.get("Retention", {})
            actual_until = retention.get("RetainUntilDate")
            if retention.get("Mode") != lock_mode or not actual_until or actual_until < retained_until:
                raise RuntimeError("S3 Object Lock retention read-back did not match the requested retention.")
            immutable = True
            verified_retain_until = actual_until
        return {
            "provider": "aws_s3", "uri": f"s3://{EVIDENCE_ARCHIVE_BUCKET}/{key}",
            "sha256": digest, "object_lock_mode": lock_mode if immutable else None,
            "retain_until": verified_retain_until.isoformat() if verified_retain_until else None,
            "version_id": version_id, "immutable": immutable,
        }

    # Developer/test archive only. A local path cannot provide WORM guarantees.
    root = (STORAGE_DIR / "trust-evidence-archive").resolve()
    root.mkdir(parents=True, exist_ok=True)
    clean = object_key.replace("\\", "/").lstrip("/")
    if any(part in {"", ".", ".."} for part in Path(clean).parts):
        raise ValueError("Invalid archive object key.")
    path = (root / clean).resolve()
    if root not in path.parents:
        raise ValueError("Archive path escaped configured storage root.")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise RuntimeError("An archive object with this key already exists with different content.")
    if not path.exists():
        path.write_bytes(payload)
        try:
            os.chmod(path, 0o440)
        except OSError:
            pass
    return {"provider": "local_filesystem", "uri": str(path), "sha256": digest,
            "object_lock_mode": None, "retain_until": None, "version_id": None,
            "immutable": False}


def provider_readiness() -> dict[str, Any]:
    return {
        "signing": {"provider": TRUST_SIGNING_PROVIDER,
                    "configured": bool(TRUST_SIGNING_PROVIDER == "local_hmac" or TRUST_KMS_KEY_ID),
                    "kms_key_configured": bool(TRUST_KMS_KEY_ID),
                    "algorithm": TRUST_KMS_SIGNING_ALGORITHM if TRUST_SIGNING_PROVIDER == "aws_kms" else "HMAC-SHA256",
                    "production_grade": TRUST_SIGNING_PROVIDER == "aws_kms"},
        "archive": {"provider": "aws_s3" if EVIDENCE_ARCHIVE_BUCKET else "local_filesystem",
                    "configured": bool(EVIDENCE_ARCHIVE_BUCKET),
                    "bucket_configured": bool(EVIDENCE_ARCHIVE_BUCKET),
                    "object_lock_requested": EVIDENCE_ARCHIVE_RETENTION_DAYS > 0,
                    "retention_days": EVIDENCE_ARCHIVE_RETENTION_DAYS,
                    "mode": EVIDENCE_ARCHIVE_MODE if EVIDENCE_ARCHIVE_RETENTION_DAYS > 0 else None,
                    "production_grade": bool(EVIDENCE_ARCHIVE_BUCKET and EVIDENCE_ARCHIVE_RETENTION_DAYS > 0)},
    }
