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
# The expected revision used to be the literal '0003_infrastructure_hardening', and
# the comparison was `| grep -qx ok`: once migration 0004 existed the check could
# never pass again, and when it failed it failed *silently* — grep -q prints nothing,
# so the job died with exit 1 and no line saying why. Nobody saw it because this
# script had never run: the job died at migration 0001 until 2026-08-03.
#
# The head is now derived from the migration files themselves — the revision that no
# other migration names as its down_revision — so it cannot drift again, and a
# mismatch says which revision was found and which was expected.
expected_head="$(python3 - "$root/apps/api/migrations/versions" <<'PY'
import ast, pathlib, sys

revisions, parents = set(), set()
for path in sorted(pathlib.Path(sys.argv[1]).glob("*.py")):
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            first = node.targets[0]
            target = first.id if isinstance(first, ast.Name) else None
        value = getattr(node, "value", None)
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        if target == "revision":
            revisions.add(value.value)
        elif target == "down_revision":
            parents.add(value.value)
heads = sorted(revisions - parents)
if len(heads) != 1:
    raise SystemExit(f"expected exactly one migration head, found {heads}")
print(heads[0])
PY
)"
actual_head="$(psql "$KORPUS_RESTORE_DATABASE_URL" -v ON_ERROR_STOP=1 -Atc \
  "SELECT version_num FROM alembic_version")"
if [[ "$actual_head" != "$expected_head" ]]; then
  echo "restored database is at migration '$actual_head', expected '$expected_head'" >&2
  exit 65
fi
printf 'restored backup encrypted under key id %s at migration %s\n' \
  "$manifest_key_id" "$actual_head" >&2
