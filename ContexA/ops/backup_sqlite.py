"""Consistent online backup of the local SQLite database (safe while the API is running).

Usage:  python ops/backup_sqlite.py [--db backend/contexa.db] [--out backups] [--keep 14]
Uses SQLite's backup API, verifies integrity, writes a SHA-256 file and prunes old backups.
"""
from __future__ import annotations

import argparse
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(root / "backend" / "contexa.db"))
    ap.add_argument("--out", default=str(root / "backups"))
    ap.add_argument("--keep", type=int, default=14, help="number of newest backups to keep")
    args = ap.parse_args()
    src_path = Path(args.db)
    if not src_path.exists():
        print(f"Database not found: {src_path}")
        return 1
    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"contexa-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.db"
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    with dst:
        src.backup(dst)
    result = dst.execute("PRAGMA integrity_check").fetchone()[0]
    src.close(); dst.close()
    if result != "ok":
        target.unlink(missing_ok=True)
        print(f"Integrity check failed: {result}")
        return 2
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    Path(str(target) + ".sha256").write_text(f"{digest}  {target.name}\n")
    for old in sorted(out_dir.glob("contexa-*.db"))[:-args.keep]:
        old.unlink(); Path(str(old) + ".sha256").unlink(missing_ok=True)
    print(f"Backup OK: {target}\nSHA-256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
