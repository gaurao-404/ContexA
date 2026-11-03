#!/usr/bin/env bash
set -euo pipefail
umask 077
: "${DATABASE_URL:?Set DATABASE_URL to the PostgreSQL restore target}"
: "${BACKUP_FILE:?Set BACKUP_FILE to a .dump file created by backup_postgres.sh}"
if [[ ! -f "$BACKUP_FILE" ]]; then echo "Backup file not found: $BACKUP_FILE" >&2; exit 2; fi
if [[ ! -f "$BACKUP_FILE.sha256" ]]; then echo "Checksum file missing: $BACKUP_FILE.sha256" >&2; exit 2; fi
(cd "$(dirname "$BACKUP_FILE")" && sha256sum -c "$(basename "$BACKUP_FILE").sha256")
DB_NAME="$(python - "$DATABASE_URL" <<'PY'
import sys
from urllib.parse import urlparse
print(urlparse(sys.argv[1]).path.lstrip('/'))
PY
)"
: "${RESTORE_CONFIRM:?Set RESTORE_CONFIRM to the exact target database name to continue}"
if [[ "$RESTORE_CONFIRM" != "$DB_NAME" ]]; then echo "RESTORE_CONFIRM did not match target database '$DB_NAME'. Restore cancelled." >&2; exit 3; fi
echo "WARNING: this restore replaces objects in database '$DB_NAME'."
pg_restore --clean --if-exists --no-owner --no-acl --dbname "$DATABASE_URL" "$BACKUP_FILE"
echo "Restore completed. Run application smoke tests and audit verification before reopening traffic."
