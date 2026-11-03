"""Private upload storage adapter: local private directory or optional S3-compatible bucket."""
from __future__ import annotations

from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote

from .config import (STORAGE_DIR, S3_BUCKET, S3_REGION, S3_ENDPOINT_URL,
                     S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_PREFIX, S3_FORCE_PATH_STYLE, S3_SERVER_SIDE_ENCRYPTION)


def _s3_client():
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise RuntimeError("S3 storage is configured but boto3 is missing. Install backend requirements.") from exc
    kwargs = {"region_name": S3_REGION, "config": Config(s3={"addressing_style": "path" if S3_FORCE_PATH_STYLE else "auto"})}
    if S3_ENDPOINT_URL:
        kwargs["endpoint_url"] = S3_ENDPOINT_URL
    if S3_ACCESS_KEY_ID:
        kwargs["aws_access_key_id"] = S3_ACCESS_KEY_ID
        kwargs["aws_secret_access_key"] = S3_SECRET_ACCESS_KEY
    return boto3.client("s3", **kwargs)


def store_bytes(data: bytes, key: str, content_type: str) -> str:
    raw_key = key.replace("\\", "/")
    candidate = PurePosixPath(raw_key)
    if "\x00" in raw_key or candidate.is_absolute() or any(part in {".", ".."} for part in candidate.parts) or (candidate.parts and ":" in candidate.parts[0]):
        raise ValueError("Unsafe storage key.")
    normalized = "/".join(part for part in candidate.parts if part)
    if not normalized:
        raise ValueError("Storage key cannot be empty.")
    if S3_BUCKET:
        prefix = S3_PREFIX.strip("/").replace("\\", "/")
        if "\x00" in prefix or any(part in {".", ".."} for part in PurePosixPath(prefix).parts):
            raise ValueError("Unsafe S3 storage prefix.")
        object_key = f"{prefix}/{normalized}".strip("/") if prefix else normalized
        kwargs = {"Bucket": S3_BUCKET, "Key": object_key, "Body": data, "ContentType": content_type}
        if S3_SERVER_SIDE_ENCRYPTION:
            kwargs["ServerSideEncryption"] = S3_SERVER_SIDE_ENCRYPTION
        _s3_client().put_object(**kwargs)
        return f"s3://{S3_BUCKET}/{quote(object_key, safe='/')}"
    path = (STORAGE_DIR / normalized).resolve()
    if STORAGE_DIR not in path.parents:
        raise ValueError("Unsafe storage key.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)


def read_bytes(stored_path: str, fallback_data: bytes | None = None) -> bytes:
    if fallback_data is not None:
        return fallback_data
    if stored_path.startswith("s3://"):
        target = stored_path[len("s3://"):]
        bucket, _, key = target.partition("/")
        decoded_key = unquote(key)
        if not S3_BUCKET or bucket != S3_BUCKET or not decoded_key or any(part in {".", ".."} for part in PurePosixPath(decoded_key).parts):
            raise FileNotFoundError("Stored object reference is outside the configured private bucket.")
        response = _s3_client().get_object(Bucket=bucket, Key=decoded_key)
        return response["Body"].read()
    path = Path(stored_path).resolve()
    if STORAGE_DIR not in path.parents:
        raise FileNotFoundError("Stored upload path is outside the private storage root.")
    return path.read_bytes()


def delete_object(stored_path: str) -> None:
    if not stored_path:
        return
    if stored_path.startswith("s3://"):
        target = stored_path[len("s3://"):]
        bucket, _, key = target.partition("/")
        decoded_key = unquote(key)
        if not S3_BUCKET or bucket != S3_BUCKET or not decoded_key or any(part in {".", ".."} for part in PurePosixPath(decoded_key).parts):
            raise FileNotFoundError("Stored object reference is outside the configured private bucket.")
        _s3_client().delete_object(Bucket=bucket, Key=decoded_key)
        return
    path = Path(stored_path).resolve()
    if STORAGE_DIR in path.parents:
        path.unlink(missing_ok=True)
