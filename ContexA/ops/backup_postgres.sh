#!/usr/bin/env bash
set -euo pipefail
umask 077
: "${DATABASE_URL:?Set DATABASE_URL to the PostgreSQL connection string}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$BACKUP_DIR/contexa-${STAMP}.dump"
pg_dump --format=custom --no-owner --no-acl --file "$OUT" "$DATABASE_URL"
sha256sum "$OUT" > "$OUT.sha256"
echo "Backup created: $OUT"
echo "Checksum created: $OUT.sha256"
echo "Store both files in encrypted, access-controlled backup storage outside the application host."
