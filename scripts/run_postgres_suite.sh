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
#   scripts/run_postgres_suite.sh --targeted apps/api/tests/test_postgres_integration.py
#
# An existing database can be used instead by setting KORPUS_TEST_DATABASE_URL and
# KORPUS_TEST_DATABASE_ADMIN_URL; the script then only runs the suite.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
if [[ -n "${PYTHON:-}" ]]; then
  python_bin="$PYTHON"
elif [[ -x "$root/apps/api/.venv/bin/python" ]]; then
  python_bin="$root/apps/api/.venv/bin/python"
else
  python_bin="$(command -v python3 || command -v python)"
fi

targets=(apps/api/tests)
if [[ "${1:-}" == --targeted ]]; then
  shift
  if [[ "$#" -eq 0 ]]; then
    echo "--targeted requires explicit test files under apps/api/tests" >&2
    exit 2
  fi
  targets=("$@")
  for target in "${targets[@]}"; do
    if [[ "$target" != apps/api/tests/*.py || "$target" == *..* || ! -f "$root/$target" ]]; then
      echo "invalid targeted PostgreSQL test file: $target" >&2
      exit 2
    fi
  done
  set --
fi

if [[ -n "${KORPUS_TEST_DATABASE_URL:-}" ]]; then
  exec env PYTHONPATH="$root/apps/api/src" "$python_bin" -m pytest -p no:cacheprovider "${targets[@]}" --no-cov "$@"
fi

# Відсутній docker — ВІДМОВА, не пропуск. Набір потрапив до нічного лану 01.09.2026
# саме тому, що прогін на СУБД розгортання дав чотири вади, невидимі на SQLite;
# «тихо не побігло» повернуло б рівно той стан, який це мало закрити.
if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required for the PostgreSQL suite; set KORPUS_TEST_DATABASE_URL to" \
       "run against an existing database instead" >&2
  exit 2
fi

image="pgvector/pgvector:0.8.5-pg17-trixie@sha256:69573b32242ca232f65871d4cb916ba7210a372b9bd74068204c1a9a57bada4f"
container="${KORPUS_PG_CONTAINER:-korpus-pg-suite}"
port="${KORPUS_PG_PORT:-55433}"
password="korpus-suite-$$"
app_password="korpus-app-$$"
authz_password="korpus-authz-$$"
review_password="korpus-review-$$"
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

# The image briefly starts an initdb server before its final process. Use the
# same stable-readiness contract as the mandatory full coverage producer. Probe
# TCP explicitly: the image's temporary setup server only exposes a Unix socket.
ready_streak=0
for _ in $(seq 1 60); do
  if docker exec "$container" pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1; then
    ready_streak=$((ready_streak + 1))
    if [[ "$ready_streak" -ge 3 ]]; then
      break
    fi
  else
    ready_streak=0
  fi
  sleep 1
done
if [[ "$ready_streak" -lt 3 ]]; then
  docker logs "$container" >&2 || true
  echo "PostgreSQL suite container did not become stably ready" >&2
  exit 69
fi

admin_url="postgresql+psycopg://postgres:${password}@127.0.0.1:${port}/${database}"
app_url="postgresql+psycopg://korpus_app:${app_password}@127.0.0.1:${port}/${database}"
authz_url="postgresql+psycopg://korpus_authz:${authz_password}@127.0.0.1:${port}/${database}"
review_url="postgresql+psycopg://korpus_review:${review_password}@127.0.0.1:${port}/${database}"

( cd apps/api && KORPUS_DATABASE_URL="$admin_url" "$python_bin" -m alembic -c alembic.ini upgrade head >/dev/null )
KORPUS_DATABASE_URL="$admin_url" KORPUS_POSTGRES_ADMIN_URL="$admin_url" \
  KORPUS_POSTGRES_APP_ROLE=korpus_app KORPUS_POSTGRES_APP_PASSWORD="$app_password" \
  KORPUS_POSTGRES_AUTHZ_ROLE=korpus_authz KORPUS_POSTGRES_AUTHZ_PASSWORD="$authz_password" \
  KORPUS_POSTGRES_REVIEW_ROLE=korpus_review KORPUS_POSTGRES_REVIEW_PASSWORD="$review_password" \
  PYTHONPATH="$root/apps/api/src" "$python_bin" scripts/prepare_postgres_role.py >/dev/null

KORPUS_TEST_DATABASE_URL="$app_url" \
KORPUS_TEST_DATABASE_ADMIN_URL="$admin_url" \
KORPUS_POSTGRES_TEST_URL="$app_url" \
KORPUS_AUTHZ_DATABASE_URL="$authz_url" \
KORPUS_REVIEW_DATABASE_URL="$review_url" \
PYTHONPATH="$root/apps/api/src" "$python_bin" -m pytest -p no:cacheprovider "${targets[@]}" --no-cov "$@"
