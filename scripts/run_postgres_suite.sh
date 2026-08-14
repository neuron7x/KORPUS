#!/usr/bin/env bash
# Run the whole test suite against a migrated PostgreSQL database.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
python_bin="${PYTHON:-$root/apps/api/.venv/bin/python}"

if [[ -n "${KORPUS_TEST_DATABASE_URL:-}" ]]; then
  if [[ -z "${KORPUS_REVIEW_DATABASE_URL:-}" || -z "${RLS_IDENTITY_DATABASE_URL:-}" ]]; then
    echo "KORPUS_REVIEW_DATABASE_URL and RLS_IDENTITY_DATABASE_URL are required with an external PostgreSQL test DB" >&2
    exit 2
  fi
  exec env PYTHONPATH="$root/apps/api/src" "$python_bin" -m pytest apps/api/tests --no-cov "$@"
fi

image="pgvector/pgvector:0.8.5-pg17-trixie@sha256:69573b32242ca232f65871d4cb916ba7210a372b9bd74068204c1a9a57bada4f"
container="${KORPUS_PG_CONTAINER:-korpus-pg-suite}"
port="${KORPUS_PG_PORT:-55433}"
password="korpus-suite-$$"
app_password="korpus-app-$$"
review_password="korpus-review-$$"
identity_password="korpus-identity-$$"
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
review_url="postgresql+psycopg://korpus_review:${review_password}@127.0.0.1:${port}/${database}"
identity_url="postgresql+psycopg://korpus_identity:${identity_password}@127.0.0.1:${port}/${database}"

(
  cd apps/api
  KORPUS_DATABASE_URL="$admin_url" "$python_bin" -m alembic -c alembic.ini upgrade head >/dev/null
)
KORPUS_DATABASE_URL="$admin_url" KORPUS_POSTGRES_ADMIN_URL="$admin_url" \
  KORPUS_POSTGRES_APP_ROLE=korpus_app KORPUS_POSTGRES_APP_PASSWORD="$app_password" \
  KORPUS_POSTGRES_REVIEW_ROLE=korpus_review KORPUS_POSTGRES_REVIEW_PASSWORD="$review_password" \
  KORPUS_POSTGRES_IDENTITY_ROLE=korpus_identity \
  KORPUS_POSTGRES_IDENTITY_PASSWORD="$identity_password" \
  PYTHONPATH="$root/apps/api/src" "$python_bin" scripts/prepare_postgres_role.py >/dev/null

KORPUS_TEST_DATABASE_URL="$app_url" \
KORPUS_TEST_DATABASE_ADMIN_URL="$admin_url" \
KORPUS_POSTGRES_TEST_URL="$app_url" \
KORPUS_REVIEW_DATABASE_URL="$review_url" \
RLS_IDENTITY_DATABASE_URL="$identity_url" \
PYTHONPATH="$root/apps/api/src" "$python_bin" -m pytest apps/api/tests --no-cov "$@"
