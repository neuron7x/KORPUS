#!/usr/bin/env bash
# Execute an encrypted SQLite backup/restore drill against a disposable current-schema
# corpus and emit the same recovery-report contract consumed by research assurance.
#
# This is deliberately CI_FIXTURE evidence. It proves the complete local recovery path
# executes, including writes after the backup and measured loss; it does not claim an
# operational RTO/RPO or production-like scale.
set -euo pipefail
umask 077

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$root"
python_bin="${PYTHON:-$(command -v python3)}"
if [[ "$python_bin" != /* ]]; then
  python_bin="$root/$python_bin"
fi
[[ -x "$python_bin" ]] || {
  echo "Python interpreter is not executable: $python_bin" >&2
  exit 69
}
work="${KORPUS_SQLITE_DRILL_WORKDIR:-$root/var/sqlite-recovery-drill}"
source_db="$work/source.db"
objects="$work/objects"
restore_dir="$work/restored"
backup_dir="$work/backups"
second_dir="$work/second-copy"
key_file="$work/backup.key"

rm -rf "$work"
mkdir -p "$work" "$objects" "$backup_dir" "$second_dir"
"$python_bin" -c 'import secrets,sys; open(sys.argv[1],"w").write(secrets.token_hex(32))' "$key_file"
chmod 600 "$key_file"

source_url="sqlite:///$source_db"
restored_url="sqlite:///$restore_dir/korpus.db"
export PYTHONPATH="$root/apps/api/src"
export KORPUS_AUDIT_HMAC_KEY="sqlite-recovery-drill-key"

echo "== migrate source =="
(
  cd apps/api
  KORPUS_DATABASE_URL="$source_url" "$python_bin" -m alembic -c alembic.ini upgrade head
)

echo "== bootstrap approved corpus =="
KORPUS_DATABASE_URL="$source_url" \
KORPUS_OBJECT_ROOT="$objects" \
KORPUS_REVIEW_SEPARATION_REQUIRED=false \
  "$python_bin" scripts/bootstrap_local.py >/dev/null

echo "== seed pre-backup recovery rows =="
KORPUS_RECOVERY_SEED_URL="$source_url" "$python_bin" scripts/seed_recovery_fixture.py >/dev/null

echo "== encrypted backup =="
backup="$({
  KORPUS_BACKUP_SQLITE_PATH="$source_db" \
  KORPUS_BACKUP_OBJECT_ROOT="$objects" \
  KORPUS_BACKUP_DIR="$backup_dir" \
  KORPUS_BACKUP_SECOND_DIR="$second_dir" \
  KORPUS_BACKUP_RETENTION_COUNT=3 \
  KORPUS_BACKUP_RETENTION_DAYS=14 \
  KORPUS_BACKUP_ENCRYPTION_KEY_FILE="$key_file" \
  KORPUS_BACKUP_KEY_ID="sqlite-drill" \
    bash scripts/backup_sqlite.sh
} | tail -n 1)"
[[ -f "$backup" ]] || { echo "backup was not produced" >&2; exit 65; }

echo "== write after backup =="
KORPUS_RECOVERY_PHASE=after-backup KORPUS_RECOVERY_SEED_URL="$source_url" \
  "$python_bin" scripts/seed_recovery_fixture.py >/dev/null

echo "== restore and verify =="
started="$("$python_bin" -c 'import time; print(time.perf_counter())')"
KORPUS_BACKUP_ENCRYPTION_KEY_FILE="$key_file" \
  bash scripts/restore_sqlite.sh "$backup" "$restore_dir" >/dev/null
ended="$("$python_bin" -c 'import time; print(time.perf_counter())')"
restore_seconds="$("$python_bin" -c 'import sys; print(float(sys.argv[2])-float(sys.argv[1]))' "$started" "$ended")"

echo "== measure =="
KORPUS_RECOVERY_SOURCE_URL="$source_url" \
KORPUS_RECOVERY_RESTORED_URL="$restored_url" \
KORPUS_RECOVERY_BACKUP_PATH="$backup" \
KORPUS_RECOVERY_RESTORE_SECONDS="$restore_seconds" \
KORPUS_RECOVERY_ENVIRONMENT_CLASS="CI_FIXTURE" \
  "$python_bin" scripts/measure_recovery.py
