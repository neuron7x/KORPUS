#!/usr/bin/env bash
# Back up the SQLite corpus, encrypted, with the same manifest the PostgreSQL path writes.
#
# `backup_postgres.sh` covers the deployment this system is designed for. It does not
# cover the one that is actually serving: the imported Drive corpus is a SQLite file,
# 1616 documents and 116 229 spans that took five hours to build, held on one disk with
# no replica. Losing it is not a data-loss incident with a recovery time — it is five
# hours of a laptop and a Drive quota, repeated.
#
# `VACUUM INTO` rather than `cp`: the database is in WAL mode and served while this runs,
# so copying the file alone captures a torn page set and silently leaves the -wal behind.
# `VACUUM INTO` takes a read transaction and writes a consistent, self-contained database.
#
# The object store is copied beside it. A corpus database without the objects it names
# restores to a system that can cite passages nobody can open.
#
#   KORPUS_BACKUP_ENCRYPTION_KEY_FILE=... KORPUS_BACKUP_KEY_ID=... scripts/backup_sqlite.sh
set -euo pipefail
umask 077

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
root="$(CDPATH= cd -- "$script_dir/.." && pwd)"

database="${KORPUS_BACKUP_SQLITE_PATH:-$root/var/korpus-ml.db}"
object_root="${KORPUS_BACKUP_OBJECT_ROOT:-$root/var/objects-ml}"
backup_dir="${KORPUS_BACKUP_DIR:-$root/var/backups/sqlite}"
retention_days="${KORPUS_BACKUP_RETENTION_DAYS:-14}"

: "${KORPUS_BACKUP_ENCRYPTION_KEY_FILE:?KORPUS_BACKUP_ENCRYPTION_KEY_FILE is required}"
: "${KORPUS_BACKUP_KEY_ID:?KORPUS_BACKUP_KEY_ID is required}"
case "$retention_days" in *[!0-9]*|'') echo "invalid retention days" >&2; exit 64;; esac
case "$KORPUS_BACKUP_KEY_ID" in *[!A-Za-z0-9._:-]*|'') echo "invalid backup key id" >&2; exit 64;; esac
[[ -r "$KORPUS_BACKUP_ENCRYPTION_KEY_FILE" ]] || { echo "backup key file is unreadable" >&2; exit 64; }
[[ -f "$database" ]] || { echo "no database at $database" >&2; exit 66; }

mkdir -p "$backup_dir"
chmod 700 "$backup_dir"
stamp="$(python3 - <<'PY'
from datetime import UTC, datetime
print(datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ"))
PY
)"

work="$backup_dir/.work-$stamp"
encrypted_tmp="$backup_dir/.korpus-$stamp.tar.enc.tmp"
plain_meta_tmp="$backup_dir/.korpus-$stamp.plain.json.tmp"
final="$backup_dir/korpus-$stamp.tar.enc"
manifest="$final.json"
manifest_tmp="$manifest.tmp"

committed=0
cleanup() {
  rm -rf "$work"
  rm -f "$encrypted_tmp" "$plain_meta_tmp" "$manifest_tmp"
  if [[ "$committed" -ne 1 ]]; then
    rm -f "$final" "$manifest"
  fi
}
trap cleanup EXIT INT TERM

mkdir -p "$work"
# A consistent snapshot of a database that is being written to. `cp` would not be one.
python3 - "$database" "$work/korpus.db" <<'PY'
import sqlite3
import sys

source, target = sys.argv[1], sys.argv[2]
connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
try:
    connection.execute("VACUUM INTO ?", (target,))
finally:
    connection.close()
PY

if [[ -d "$object_root" ]]; then
  cp -r "$object_root" "$work/objects"
fi

# Deterministic member order and no timestamps: two backups of an unchanged corpus
# produce the same plaintext, so a manifest digest that moves means the corpus moved.
tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner \
    -C "$work" -cf - . \
  | python3 "$root/scripts/backup_crypto.py" encrypt-stdin - "$encrypted_tmp" \
      --key-file "$KORPUS_BACKUP_ENCRYPTION_KEY_FILE" --metadata-file "$plain_meta_tmp"

plain_sha="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["sha256"])' "$plain_meta_tmp")"
plain_size="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["bytes"])' "$plain_meta_tmp")"
# Fail where the cause is still legible. An empty archive restores cleanly and is
# worse than no backup, because nothing about the restored system says it is empty.
if [[ "$plain_size" -le 0 ]]; then
  echo "the archive is empty: refusing to write a backup of nothing" >&2
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

# Read back what was just written rather than trusting the write. A backup nobody
# has opened is a file, not a backup.
python3 "$root/scripts/backup_manifest.py" verify \
  --manifest "$manifest" \
  --key-file "$KORPUS_BACKUP_ENCRYPTION_KEY_FILE" \
  --expected-file "$(basename "$final")" \
  --expected-key-id "$KORPUS_BACKUP_KEY_ID"
rm -f "$plain_meta_tmp"

# Read-only once written. Ransomware and a careless script both work by writing, and
# `chattr +i` needs a capability this process does not have. 0444 does not survive root
# and is not claimed to: object lock with a credential the writer does not hold is what
# does, and it is named as external in the policy report rather than implied here.
chmod 0444 "$final" "$manifest"

# A second copy, outside the working tree. It is not offsite — a fire takes both — and
# the policy report says so under its own clause rather than letting this one stand in.
second="${KORPUS_BACKUP_SECOND_DIR:-$root/var/backups/offsite}"
mkdir -p "$second"
chmod 700 "$second"
cp -p "$final" "$manifest" "$second/"
chmod 0444 "$second/$(basename "$final")" "$second/$(basename "$manifest")"

# Age *and* count. Retention by age alone assumes backups arrive about daily; thirty
# taken in one afternoon are all inside a fourteen-day window, and on 2026-08-07 that
# filled a 289 GB disk to 84 KB free — which stops the next backup, and every drill, and
# the tests. A retention policy that can fill the disk is not one.
retain_count="${KORPUS_BACKUP_RETENTION_COUNT:-3}"
prune() {
  local directory="$1"
  find "$directory" -maxdepth 1 -name 'korpus-*.tar.enc' -mtime "+$retention_days" -print0 \
    | while IFS= read -r -d '' old; do chmod u+w "$old" "$old.json" 2>/dev/null || true
        rm -f "$old" "$old.json"; done
  # shellcheck disable=SC2012 - names are timestamped and contain no newlines
  ls -t "$directory"/korpus-*.tar.enc 2>/dev/null | tail -n "+$((retain_count + 1))" \
    | while IFS= read -r old; do chmod u+w "$old" "$old.json" 2>/dev/null || true
        rm -f "$old" "$old.json"; done
}
prune "$backup_dir"
prune "$second"

printf '%s\n' "$final"
