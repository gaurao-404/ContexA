#!/usr/bin/env python3
"""Verify ContexA's configured Supabase project without printing credentials.

Run from the project root:
  python ops/verify_supabase_project.py
  python ops/verify_supabase_project.py --live

The live mode only performs read-only GET requests to Supabase Auth settings and JWKS.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get_json(url: str, *, api_key: str | None = None) -> dict:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["apikey"] = api_key
    request = Request(url, headers=headers, method="GET")
    with urlopen(request, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError(f"Unexpected HTTP status {response.status} for {url}")
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected JSON response from {url}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="also call read-only Supabase Auth/JWKS endpoints")
    parser.add_argument("--backend-env-file", type=Path, default=ROOT / ".env",
                        help="backend runtime environment file (default: .env; .env.example is a safe fallback)")
    parser.add_argument("--frontend-env-file", type=Path, default=ROOT / "frontend/.env.local",
                        help="optional local frontend environment file; ignored files are never required")
    args = parser.parse_args()

    # Do not depend on .env.production or any ignored/private file being present in a release archive.
    backend = read_env(ROOT / ".env.example")
    backend.update(read_env(args.backend_env_file))
    frontend = read_env(ROOT / "frontend/.env.example")
    frontend.update(read_env(args.frontend_env_file))
    backend.update({key: value for key, value in os.environ.items() if key in {
        "AUTH_MODE", "SUPABASE_URL", "SUPABASE_JWT_ISSUER", "SUPABASE_JWKS_URL", "SUPABASE_JWT_AUDIENCE"}})
    frontend.update({key: value for key, value in os.environ.items() if key in {
        "VITE_AUTH_MODE", "VITE_SUPABASE_URL", "VITE_SUPABASE_PUBLISHABLE_KEY"}})

    project_url = (frontend.get("VITE_SUPABASE_URL") or backend.get("SUPABASE_URL", "")).rstrip("/")
    publishable_key = frontend.get("VITE_SUPABASE_PUBLISHABLE_KEY", "")
    auth_mode = frontend.get("VITE_AUTH_MODE") or backend.get("AUTH_MODE", "")

    expected_issuer = f"{project_url}/auth/v1" if project_url else ""
    expected_jwks = f"{expected_issuer}/.well-known/jwks.json" if expected_issuer else ""
    checks = {
        "Supabase-only Auth mode": auth_mode == "supabase",
        "Project URL uses HTTPS": project_url.startswith("https://") and ".supabase.co" in project_url,
        "Backend project URL matches frontend": backend.get("SUPABASE_URL", "").rstrip("/") == project_url,
        "JWT issuer matches project": backend.get("SUPABASE_JWT_ISSUER") == expected_issuer,
        "JWKS endpoint matches project": backend.get("SUPABASE_JWKS_URL") == expected_jwks,
    }
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}  {name}")
    if not all(checks.values()):
        return 1
    print(f"Configured project: {project_url}")
    if publishable_key.startswith("sb_publishable_"):
        print("Publishable key: present (value intentionally not printed)")
    else:
        print("INFO  Browser publishable key is not set in environment/frontend/.env.local; no ignored production env file is required.")

    if not args.live:
        print("Static backend/project configuration is consistent. Use --live from a network that can reach Supabase to verify hosted endpoints.")
        return 0
    if not publishable_key.startswith("sb_publishable_"):
        print("FAIL  Set VITE_SUPABASE_PUBLISHABLE_KEY in the environment or frontend/.env.local before live verification.")
        return 2

    try:
        settings = get_json(f"{project_url}/auth/v1/settings", api_key=publishable_key)
        jwks = get_json(expected_jwks)
        keys = jwks.get("keys", [])
        if not isinstance(keys, list):
            raise RuntimeError("JWKS response does not contain a keys array.")
        print("PASS  Supabase Auth settings endpoint reachable (HTTP 200)")
        email_enabled = settings.get("external", {}).get("email") if isinstance(settings.get("external"), dict) else None
        print(f"INFO  Email provider: {'enabled' if email_enabled is True else 'disabled' if email_enabled is False else 'not exposed by settings endpoint'}")
        if not keys:
            print("FAIL  No asymmetric JWKS keys are published. Configure an ES256 or RS256 signing key in Supabase Auth.")
            return 2
        algorithms = sorted({str(item.get("alg")) for item in keys if item.get("alg")})
        print(f"PASS  JWKS endpoint reachable; {len(keys)} public key(s) published" + (f" ({', '.join(algorithms)})" if algorithms else ""))
        if algorithms and not set(algorithms).intersection({"ES256", "RS256"}):
            print("FAIL  Published signing algorithms do not match ContexA's ES256/RS256 allow-list.")
            return 2
    except HTTPError as exc:
        print(f"FAIL  Supabase returned HTTP {exc.code}; verify project settings and the publishable key.")
        return 2
    except (URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        print(f"FAIL  Live Supabase verification could not complete: {type(exc).__name__}: {exc}")
        return 2

    print("Live Supabase endpoint verification passed. This does not verify the custom token hook, redirect allow-list, SMTP, or a real user sign-in.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
