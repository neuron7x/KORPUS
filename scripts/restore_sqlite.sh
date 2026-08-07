#!/usr/bin/env bash
# Restore a corpus backup into a directory, and prove the result answers.
#
# Restoring somewhere else on purpose. A restore that overwrites the live corpus is a
# restore nobody rehearses, because rehearsing it costs the thing being protected; one
# that lands in a directory can be run on any Tuesday, which is the only kind that is
# ever known to work.
#
#   scripts/restore_sqlite.sh var/backups/sqlite/korpus-<stamp>.tar.enc var/restored
set -euo pipefail
umask 077

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
root="$(CDPATH= cd -- "$script_dir/.." && pwd)"

backup="${1:?usage: restore_sqlite.sh <backup.tar.enc> <target-dir>}"
target="${2:?usage: restore_sqlite.sh <backup.tar.enc> <target-dir>}"
: "${KORPUS_BACKUP_ENCRYPTION_KEY_FILE:?KORPUS_BACKUP_ENCRYPTION_KEY_FILE is required}"

manifest="$backup.json"
[[ -f "$backup" ]] || { echo "no backup at $backup" >&2; exit 66; }
[[ -f "$manifest" ]] || { echo "no manifest at $manifest" >&2; exit 66; }

# Before decrypting, not after. The manifest is authenticated with the same key, so a
# file that was swapped is caught here rather than by whatever the archive turns out to
# contain.
python3 "$root/scripts/backup_manifest.py" verify \
  --manifest "$manifest" \
  --key-file "$KORPUS_BACKUP_ENCRYPTION_KEY_FILE" \
  --expected-file "$(basename "$backup")" \
  --expected-key-id "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["key_id"])' "$manifest")" \
  >/dev/null

mkdir -p "$target"
# Decrypted to a file rather than piped: `backup_crypto.py decrypt` opens its
# destination with "xb" so that it can fsync it and remove it on failure, and a restore
# that half-extracted from a stream would leave a directory that looks restored.
archive="$target/.korpus-restore.tar"
rm -f "$archive"
cleanup() { rm -f "$archive"; }
trap cleanup EXIT INT TERM
python3 "$root/scripts/backup_crypto.py" decrypt "$backup" "$archive" \
  --key-file "$KORPUS_BACKUP_ENCRYPTION_KEY_FILE" >/dev/null
tar -C "$target" -xf "$archive"
rm -f "$archive"

database="$target/korpus.db"
[[ -f "$database" ]] || { echo "the archive contains no korpus.db" >&2; exit 65; }

# The check that makes this a restore rather than a file copy: the database opens, its
# integrity is intact, and it holds approved versions with spans to cite. A corpus that
# restores empty restores cleanly, and nothing about the running system would say so.
python3 - "$database" <<'PY'
import sqlite3
import sys

connection = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
try:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise SystemExit(f"restored database fails integrity_check: {integrity}")
    documents = connection.execute("SELECT count(*) FROM documents").fetchone()[0]
    approved = connection.execute(
        "SELECT count(*) FROM document_versions WHERE review_state = 'approved'"
    ).fetchone()[0]
    spans = connection.execute("SELECT count(*) FROM evidence_spans").fetchone()[0]
finally:
    connection.close()

if not (documents and approved and spans):
    raise SystemExit(
        f"restored corpus is unusable: {documents} documents, {approved} approved, {spans} spans"
    )
print(f"documents {documents} · approved {approved} · spans {spans}")
PY

# The drill is the property, not the copy. Recorded beside the backups so the retention
# policy can answer "when was this last proved" without asking anybody.
python3 - "$(dirname "$backup")/last-restore.json" "$backup" <<'PY'
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

Path(sys.argv[1]).write_text(
    json.dumps(
        {
            "restored_at": datetime.now(UTC).isoformat(),
            "backup": Path(sys.argv[2]).name,
            "interpretation": (
                "A restore was executed and the restored corpus was checked for integrity "
                "and for approved versions with spans. A backup nobody has restored is a "
                "file."
            ),
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
PY

printf '%s\n' "$database"
