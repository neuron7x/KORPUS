#!/usr/bin/env bash
# Run the whole test suite against a migrated PostgreSQL database.
#
# Every closure in this tree used to be proved on SQLite, and the admission boundary
# named that as its own ground: the two dialects have separate implementations of the
# currency filters, the retrieval projection, the integrity check and the audit head
# update, and the deployment runs on PostgreSQL. Three findings came out of the first
# run — a schema revision pin the code had outgrown, an audit verdict that called a
# delayed anchor a broken chain, and forty concurrent appends exhausting the retry
# budget — none of which SQLite could show.
#
# Usage:
#   scripts/run_postgres_suite.sh                 # start a container, run, tear down
#   KORPUS_PG_KEEP=1 scripts/run_postgres_suite.sh  # leave the container running
#
# An existing database can be used instead by setting KORPUS_TEST_DATABASE_URL and
# KORPUS_TEST_DATABASE_ADMIN_URL; the script then only runs the suite.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
python_bin="${PYTHON:-$root/apps/api/.venv/bin/python}"

if [[ -n "${KORPUS_TEST_DATABASE_URL:-}" ]]; then
  exec env PYTHONPATH="$root/apps/api/src" "$python_bin" -m pytest apps/api/tests --no-cov "$@"
fi

image="pgvector/pgvector:0.8.5-pg17-trixie"
container="${KORPUS_PG_CONTAINER:-korpus-pg-suite}"
port="${KORPUS_PG_PORT:-55433}"
password="korpus-suite-$$"
app_password="korpus-app-$$"
database="korpus_suite"

cleanup() {
  if [[ -z "${KORPUS_PG_KEEP:-}" ]]; then
    docker rm -f "$container" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

docker rm -f "$container" >/dev/null 2>&1 || true
docker run -d --name "$container" \
  -e POSTGRES_PASSWORD="$password" -e POSTGRES_DB="$database" -e POSTGRES_USER=postgres \
  -p "127.0.0.1:${port}:5432" "$image" >/dev/null

for _ in $(seq 1 60); do
  if docker exec "$container" pg_isready -U postgres >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$container" pg_isready -U postgres >/dev/null

admin_url="postgresql+psycopg://postgres:${password}@127.0.0.1:${port}/${database}"
app_url="postgresql+psycopg://korpus_app:${app_password}@127.0.0.1:${port}/${database}"

( cd apps/api && KORPUS_DATABASE_URL="$admin_url" "$python_bin" -m alembic -c alembic.ini upgrade head >/dev/null )
KORPUS_DATABASE_URL="$admin_url" KORPUS_POSTGRES_ADMIN_URL="$admin_url" \
  KORPUS_POSTGRES_APP_ROLE=korpus_app KORPUS_POSTGRES_APP_PASSWORD="$app_password" \
  PYTHONPATH="$root/apps/api/src" "$python_bin" scripts/prepare_postgres_role.py >/dev/null

KORPUS_TEST_DATABASE_URL="$app_url" \
KORPUS_TEST_DATABASE_ADMIN_URL="$admin_url" \
KORPUS_POSTGRES_TEST_URL="$app_url" \
PYTHONPATH="$root/apps/api/src" "$python_bin" -m pytest apps/api/tests --no-cov "$@"
