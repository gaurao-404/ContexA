#!/usr/bin/env python3
"""Independently verify a ContexA AWS KMS Trust Passport bundle offline.

Usage:
  python ops/verify_passport_signature.py passport-verification-bundle.json
  python ops/verify_passport_signature.py passport-verification-bundle.json approved-asset.pdf

The bundle contains the signed canonical manifest, the detached KMS signature,
and the KMS public key. Verification does not call AWS or ContexA. An optional
asset path is SHA-256 checked against the signed manifest's asset_sha256 field.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.cloud_providers import verify_manifest  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="JSON downloaded/copied from the public Trust Passport page")
    parser.add_argument("asset", nargs="?", type=Path, help="Optional original asset file to hash")
    args = parser.parse_args()

    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    manifest = bundle.get("manifest")
    signature = dict(bundle.get("signature") or {})
    signature.setdefault("provider", bundle.get("provider"))
    if not isinstance(manifest, dict) or signature.get("provider") != "aws_kms":
        print("FAIL: bundle must contain a signed manifest and an AWS KMS public-key signature.", file=sys.stderr)
        return 2
    if not signature.get("public_key_b64"):
        print("FAIL: public key is missing; this bundle cannot be independently verified offline.", file=sys.stderr)
        return 2

    valid = verify_manifest(manifest, signature)
    if not valid:
        print("FAIL: signature or manifest digest is invalid.", file=sys.stderr)
        return 1
    print("PASS: AWS KMS detached signature verified using the included public key.")
    print(f"Algorithm: {signature.get('algorithm')}")
    print(f"KMS key:   {signature.get('key_id')}")
    print(f"Manifest:  {signature.get('manifest_sha256')}")
    print(f"Passport:  {bundle.get('passport_id', 'unknown')}")

    if args.asset:
        actual_asset_hash = hashlib.sha256(args.asset.read_bytes()).hexdigest()
        expected_asset_hash = str(manifest.get("asset_sha256", ""))
        if not expected_asset_hash or actual_asset_hash != expected_asset_hash:
            print("FAIL: original asset SHA-256 does not match the signed manifest.", file=sys.stderr)
            return 1
        print(f"PASS: original asset SHA-256 matches ({actual_asset_hash}).")
    else:
        print("NOTE: no original asset supplied; only the signed manifest was verified.")
    print("NOTICE: a valid signature proves the manifest was signed and unchanged; it does not prove the factual truth of every claim inside it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
