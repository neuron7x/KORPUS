#!/usr/bin/env bash
set -euo pipefail
umask 077

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
root="$(CDPATH= cd -- "$script_dir/.." && pwd)"

: "${KORPUS_RESTORE_DATABASE_URL:?KORPUS_RESTORE_DATABASE_URL is required}"
: "${KORPUS_BACKUP_ENCRYPTION_KEY_FILE:?KORPUS_BACKUP_ENCRYPTION_KEY_FILE is required}"
: "${KORPUS_BACKUP_KEY_ID:?KORPUS_BACKUP_KEY_ID is required}"
backup="${1:?usage: restore_postgres.sh BACKUP.dump.enc}"
manifest="$backup.json"
[[ -r "$backup" ]] || { echo "backup is unreadable" >&2; exit 66; }
[[ -r "$manifest" ]] || { echo "backup manifest is missing" >&2; exit 66; }
[[ -r "$KORPUS_BACKUP_ENCRYPTION_KEY_FILE" ]] || { echo "backup key file is unreadable" >&2; exit 64; }

verified_manifest="$(python3 "$root/scripts/backup_manifest.py" verify \
  --manifest "$manifest" \
  --key-file "$KORPUS_BACKUP_ENCRYPTION_KEY_FILE" \
  --expected-file "$(basename "$backup")" \
  --expected-key-id "$KORPUS_BACKUP_KEY_ID")" || { echo "backup manifest verification failed" >&2; exit 65; }
read_manifest() { python3 -c 'import json,sys; print(json.loads(sys.argv[1])[sys.argv[2]])' "$verified_manifest" "$1"; }
expected_cipher="$(read_manifest sha256)"
expected_plain="$(read_manifest plaintext_sha256)"
manifest_key_id="$(read_manifest key_id)"
expected_bytes="$(read_manifest bytes)"
expected_plain_bytes="$(read_manifest plaintext_bytes)"
actual_size="$(wc -c < "$backup" | tr -d ' ')"
[[ "$actual_size" = "$expected_bytes" ]] || { echo "encrypted backup size mismatch" >&2; exit 65; }
actual_cipher="$(sha256sum "$backup" | awk '{print $1}')"
[[ "$actual_cipher" = "$expected_cipher" ]] || { echo "encrypted backup checksum mismatch" >&2; exit 65; }
restore_tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/korpus-restore.XXXXXX")"
chmod 700 "$restore_tmp_dir"
plain_tmp="$restore_tmp_dir/restore.dump"
plain_meta="$restore_tmp_dir/restore.meta.json"
cleanup() { rm -rf "$restore_tmp_dir"; }
trap cleanup EXIT INT TERM
python3 "$root/scripts/backup_crypto.py" decrypt "$backup" "$plain_tmp" \
  --key-file "$KORPUS_BACKUP_ENCRYPTION_KEY_FILE" --metadata-file "$plain_meta"
actual_plain="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["sha256"])' "$plain_meta")"
actual_plain_bytes="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["bytes"])' "$plain_meta")"
[[ "$actual_plain" = "$expected_plain" ]] || { echo "decrypted backup checksum mismatch" >&2; exit 65; }
[[ "$actual_plain_bytes" = "$expected_plain_bytes" ]] || { echo "decrypted backup size mismatch" >&2; exit 65; }
pg_restore --list "$plain_tmp" >/dev/null
pg_restore --dbname="$KORPUS_RESTORE_DATABASE_URL" \
  --clean --if-exists --no-owner --no-privileges --exit-on-error --single-transaction "$plain_tmp"
psql "$KORPUS_RESTORE_DATABASE_URL" -v ON_ERROR_STOP=1 -Atc \
  "SELECT CASE WHEN version_num = '0003_infrastructure_hardening' THEN 'ok' ELSE version_num END FROM alembic_version" \
  | grep -qx ok
printf 'restored backup encrypted under key id %s\n' "$manifest_key_id" >&2
