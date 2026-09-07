#!/usr/bin/env bash
# The backup/restore drill, on a machine with docker and no PostgreSQL client tooling.
#
# `api:postgres-and-restore` in .gitlab-ci.yml runs this in CI, where `pg_dump`,
# `pg_restore` and `psql` are on the PATH. On a developer machine they usually are not,
# and the consequence was that `assemble_assurance.py` could never reach PASS locally:
# `recovery_drill_executed` is false without `var/recovery-report.json`, and that file
# only exists after a drill. A release step that can only run in CI is a release step
# nobody rehearses.
#
# So the client tools are borrowed from the database container itself — the same image the
# suite already uses — and everything that needs the repository's Python (the encryption,
# the manifest, the measurement) runs here. The bytes cross the boundary through pipes:
# `pg_dump` writes to stdout inside the container, `backup_crypto.py` encrypts on this
# side, and no plaintext dump is ever written to disk.
#
# Usage:
#   scripts/run_recovery_drill.sh
#   KORPUS_PG_KEEP=1 scripts/run_recovery_drill.sh   # leave the container running
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
python_bin="${PYTHON:-$root/apps/api/.venv/bin/python}"

image="pgvector/pgvector:0.8.5-pg17-trixie@sha256:69573b32242ca232f65871d4cb916ba7210a372b9bd74068204c1a9a57bada4f"
container="${KORPUS_PG_CONTAINER:-korpus-pg-drill}"
port="${KORPUS_PG_PORT:-55434}"
password="korpus-drill-$$"
app_password="korpus-app-$$"
authz_password="korpus-authz-$$"
source_db="korpus_drill"
restored_db="korpus_drill_restore"

cleanup() {
  if [[ -z "${KORPUS_PG_KEEP:-}" ]]; then
    docker rm -f "$container" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

docker rm -f "$container" >/dev/null 2>&1 || true
docker run -d --name "$container" \
  -e POSTGRES_PASSWORD="$password" -e POSTGRES_DB="$source_db" -e POSTGRES_USER=postgres \
  -p "127.0.0.1:${port}:5432" "$image" >/dev/null

for _ in $(seq 1 90); do
  if docker exec "$container" pg_isready -U postgres >/dev/null 2>&1; then break; fi
  sleep 1
done
docker exec "$container" pg_isready -U postgres >/dev/null

admin_url="postgresql+psycopg://postgres:${password}@127.0.0.1:${port}/${source_db}"
app_url="postgresql+psycopg://korpus_app:${app_password}@127.0.0.1:${port}/${source_db}"
restored_admin_url="postgresql+psycopg://postgres:${password}@127.0.0.1:${port}/${restored_db}"
restored_app_url="postgresql+psycopg://korpus_app:${app_password}@127.0.0.1:${port}/${restored_db}"
# Роль БРОКЕРА. `measure_recovery.py` вимагає її з 04.09.2026, а цей скрипт востаннє
# чіпали 12.08 — тож постгресний прогін відновлення був МЕРТВИЙ два дні: він доходив
# до вимірювача і той відмовляв («URL брокера обов'язковий»), а предикат
# `trusted_recovery_attestation` не мав ЖОДНОЇ дороги до закриття. Вічне PENDING —
# це недосяжність, не очікування.
authz_url="postgresql+psycopg://korpus_authz:${authz_password}@127.0.0.1:${port}/${source_db}"
restored_authz_url="postgresql+psycopg://korpus_authz:${authz_password}@127.0.0.1:${port}/${restored_db}"

export PYTHONPATH="$root/apps/api/src"
export KORPUS_AUDIT_HMAC_KEY="recovery-drill-key"

echo "== migrate =="
( cd apps/api && KORPUS_DATABASE_URL="$admin_url" "$python_bin" -m alembic -c alembic.ini upgrade head )
KORPUS_DATABASE_URL="$admin_url" KORPUS_POSTGRES_APP_ROLE=korpus_app \
  KORPUS_POSTGRES_APP_PASSWORD="$app_password" \
  KORPUS_POSTGRES_AUTHZ_ROLE=korpus_authz KORPUS_POSTGRES_AUTHZ_PASSWORD="$authz_password" \
  "$python_bin" scripts/prepare_postgres_role.py >/dev/null

echo "== seed =="
KORPUS_RECOVERY_SEED_URL="$admin_url" "$python_bin" scripts/seed_recovery_fixture.py

# The key is generated per run and never leaves this directory. It is not packaged:
# `scripts/package_release.py` excludes var/ entirely.
mkdir -p var
key_file="var/backup-encryption.key"
"$python_bin" -c "import secrets,pathlib;pathlib.Path('$key_file').write_text(secrets.token_hex(32))"
chmod 600 "$key_file"

echo "== back up =="
backup_dir="$root/var/backups/postgres"
mkdir -p "$backup_dir"; chmod 700 "$backup_dir"
stamp="$("$python_bin" -c "from datetime import UTC,datetime;print(datetime.now(UTC).strftime('%Y%m%dT%H%M%S.%fZ'))")"
final="$backup_dir/korpus-$stamp.dump.enc"
plain_meta="$backup_dir/.korpus-$stamp.plain.json.tmp"

# pg_dump runs inside the container; its stdout is this pipeline's stdin. No plaintext
# dump touches either filesystem.
docker exec "$container" pg_dump \
  --dbname="postgresql://postgres:${password}@127.0.0.1:5432/${source_db}" \
  --format=custom --compress=6 --no-owner --no-privileges \
  | "$python_bin" scripts/backup_crypto.py encrypt-stdin - "$final" \
      --key-file "$key_file" --metadata-file "$plain_meta"

plain_sha="$("$python_bin" -c "import json,sys;print(json.load(open(sys.argv[1]))['sha256'])" "$plain_meta")"
plain_size="$("$python_bin" -c "import json,sys;print(json.load(open(sys.argv[1]))['bytes'])" "$plain_meta")"
if [[ "$plain_size" -le 0 ]]; then
  echo "pg_dump produced no output: refusing to write an empty backup" >&2
  exit 65
fi
encrypted_sha="$(sha256sum "$final" | awk '{print $1}')"
encrypted_size="$(wc -c < "$final" | tr -d ' ')"
"$python_bin" scripts/backup_manifest.py create \
  --output "$final.json" --file "$(basename "$final")" --key-file "$key_file" \
  --key-id drill --created-at "$stamp" --bytes "$encrypted_size" --sha256 "$encrypted_sha" \
  --plaintext-bytes "$plain_size" --plaintext-sha256 "$plain_sha" >/dev/null
rm -f "$plain_meta"
chmod 400 "$final"

echo "== write after the backup =="
# These rows exist so "lost nothing" is a result the drill could have failed to produce.
# A copy of a database nobody wrote to loses nothing however broken the restore is.
KORPUS_RECOVERY_PHASE=after-backup KORPUS_RECOVERY_SEED_URL="$admin_url" \
  "$python_bin" scripts/seed_recovery_fixture.py

echo "== restore =="
docker exec "$container" psql -U postgres -v ON_ERROR_STOP=1 -d postgres \
  -c "DROP DATABASE IF EXISTS ${restored_db}" -c "CREATE DATABASE ${restored_db}" >/dev/null

restore_started="$(date +%s.%N)"
# A directory, not `mktemp` on the file: `backup_crypto.py decrypt` refuses to overwrite
# an existing destination, and mktemp's whole job is to create one.
restore_dir="$(mktemp -d "${TMPDIR:-/tmp}/korpus-restore.XXXXXX")"
chmod 700 "$restore_dir"
plain_tmp="$restore_dir/restore.dump"
# Decrypted here, where the key is, and streamed in. The plaintext dump exists on this
# side only as a mode-600 temporary file that is removed on the way out — it never lands
# in the container's filesystem, where anything else on the image could read it.
"$python_bin" scripts/backup_crypto.py decrypt "$final" "$plain_tmp" \
  --key-file "$key_file" --metadata-file "$plain_tmp.meta.json"
docker exec -i "$container" pg_restore \
  --dbname="postgresql://postgres:${password}@127.0.0.1:5432/${restored_db}" \
  --clean --if-exists --no-owner --no-privileges --exit-on-error --single-transaction \
  < "$plain_tmp"
rm -rf "$restore_dir"
restore_seconds="$("$python_bin" -c "import sys;print(float(sys.argv[2])-float(sys.argv[1]))" "$restore_started" "$(date +%s.%N)")"

# The restored copy needs the least-privilege role too: every count below is taken
# through it, because RLS does not apply to a superuser and a superuser count is a number
# about the table rather than about what the application can recover.
KORPUS_DATABASE_URL="$restored_admin_url" KORPUS_POSTGRES_APP_ROLE=korpus_app \
  KORPUS_POSTGRES_APP_PASSWORD="$app_password" \
  KORPUS_POSTGRES_AUTHZ_ROLE=korpus_authz KORPUS_POSTGRES_AUTHZ_PASSWORD="$authz_password" \
  "$python_bin" scripts/prepare_postgres_role.py >/dev/null

echo "== verify =="
KORPUS_POSTGRES_TEST_URL="$restored_app_url" KORPUS_AUTHZ_DATABASE_URL="$restored_authz_url" \
  "$python_bin" scripts/verify_postgres_restore.py

KORPUS_RECOVERY_SOURCE_URL="$app_url" \
KORPUS_RECOVERY_RESTORED_URL="$restored_app_url" \
KORPUS_RECOVERY_SOURCE_AUTHZ_URL="$authz_url" \
KORPUS_RECOVERY_RESTORED_AUTHZ_URL="$restored_authz_url" \
KORPUS_RECOVERY_BACKUP_PATH="$final" \
KORPUS_RECOVERY_RESTORE_SECONDS="$restore_seconds" \
  "$python_bin" scripts/measure_recovery.py
