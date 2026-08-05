#!/usr/bin/env bash
set -euo pipefail
umask 077

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
root="$(CDPATH= cd -- "$script_dir/.." && pwd)"

: "${KORPUS_BACKUP_DATABASE_URL:?KORPUS_BACKUP_DATABASE_URL is required}"
: "${KORPUS_BACKUP_ENCRYPTION_KEY_FILE:?KORPUS_BACKUP_ENCRYPTION_KEY_FILE is required}"
: "${KORPUS_BACKUP_KEY_ID:?KORPUS_BACKUP_KEY_ID is required}"
backup_dir="${KORPUS_BACKUP_DIR:-$root/var/backups/postgres}"
retention_days="${KORPUS_BACKUP_RETENTION_DAYS:-14}"
case "$retention_days" in *[!0-9]*|'') echo "invalid retention days" >&2; exit 64;; esac
case "$KORPUS_BACKUP_KEY_ID" in *[!A-Za-z0-9._:-]*|'') echo "invalid backup key id" >&2; exit 64;; esac
[[ -r "$KORPUS_BACKUP_ENCRYPTION_KEY_FILE" ]] || { echo "backup key file is unreadable" >&2; exit 64; }

mkdir -p "$backup_dir"
chmod 700 "$backup_dir"
stamp="$(python3 - <<'PY'
from datetime import UTC, datetime
print(datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ"))
PY
)"
encrypted_tmp="$backup_dir/.korpus-$stamp.dump.enc.tmp"
plain_meta_tmp="$backup_dir/.korpus-$stamp.plain.json.tmp"
final="$backup_dir/korpus-$stamp.dump.enc"
manifest="$final.json"
manifest_tmp="$manifest.tmp"

committed=0
cleanup() {
  rm -f "$encrypted_tmp" "$plain_meta_tmp" "$manifest_tmp"
  if [[ "$committed" -ne 1 ]]; then
    rm -f "$final" "$manifest"
  fi
}
trap cleanup EXIT INT TERM

# No plaintext dump file is created: pg_dump bytes flow directly into authenticated
# encryption. `--file=-` was removed on 2026-08-03: pg_dump wrote a file literally
# named "-" in the working directory and left stdout empty, so the pipeline encrypted
# zero bytes and the run only failed three steps later, in manifest validation, as
# "invalid backup manifest field: plaintext_bytes". Omitting the flag is the
# documented way to send the archive to stdout. This path had never executed before —
# the job died at migration 0001 until today.
pg_dump --dbname="$KORPUS_BACKUP_DATABASE_URL" \
  --format=custom --compress=6 --no-owner --no-privileges \
  | python3 "$root/scripts/backup_crypto.py" encrypt-stdin - "$encrypted_tmp" \
      --key-file "$KORPUS_BACKUP_ENCRYPTION_KEY_FILE" --metadata-file "$plain_meta_tmp"

plain_sha="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["sha256"])' "$plain_meta_tmp")"
plain_size="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["bytes"])' "$plain_meta_tmp")"
# Fail here, where the cause is still legible, rather than in manifest validation.
# An empty dump means pg_dump produced nothing on stdout — a backup of a database
# that was never read is worse than no backup, because it restores cleanly.
if [[ "$plain_size" -le 0 ]]; then
  echo "pg_dump produced no output: refusing to write an empty backup" >&2
  exit 65
fi
encrypted_sha="$(sha256sum "$encrypted_tmp" | awk '{print $1}')"
encrypted_size="$(wc -c < "$encrypted_tmp" | tr -d ' ')"
mv "$encrypted_tmp" "$final"
python3 "$root/scripts/backup_manifest.py" create \
  --output "$manifest_tmp" \
  --key-file "$KORPUS_BACKUP_ENCRYPTION_KEY_FILE" \
  --created-at "$stamp" \
  --sha256 "$encrypted_sha" \
  --bytes "$encrypted_size" \
  --plaintext-sha256 "$plain_sha" \
  --plaintext-bytes "$plain_size" \
  --file "$(basename "$final")" \
  --key-id "$KORPUS_BACKUP_KEY_ID"
mv "$manifest_tmp" "$manifest"
committed=1
python3 - "$backup_dir" <<'PY'
import os, sys
fd = os.open(sys.argv[1], os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
try:
    os.fsync(fd)
finally:
    os.close(fd)
PY
rm -f "$plain_meta_tmp"
find "$backup_dir" -type f \( -name 'korpus-*.dump.enc' -o -name 'korpus-*.dump.enc.json' \) -mtime "+$retention_days" -delete
printf '%s\n' "$final"
