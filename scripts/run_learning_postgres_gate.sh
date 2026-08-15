#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${PYTHON:-$root/apps/api/.venv/bin/python}"
image="pgvector/pgvector:0.8.5-pg17-trixie@sha256:69573b32242ca232f65871d4cb916ba7210a372b9bd74068204c1a9a57bada4f"
container="${KORPUS_LEARNING_PG_CONTAINER:-korpus-learning-gate}"
port="${KORPUS_LEARNING_PG_PORT:-55434}"
password="korpus-learning-gate-$$"
database="korpus_learning_gate"

if [[ ! -x "$python_bin" ]]; then
  echo "Python environment missing: $python_bin" >&2
  exit 2
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 2
fi
if ! "$python_bin" -c 'import psycopg' >/dev/null 2>&1; then
  echo "psycopg is required; run: cd apps/api && uv pip install --python .venv/bin/python -e '.[dev,postgres]'" >&2
  exit 2
fi

cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cleanup
docker run -d --name "$container" \
  -e POSTGRES_PASSWORD="$password" \
  -e POSTGRES_DB="$database" \
  -e POSTGRES_USER=postgres \
  -p "127.0.0.1:${port}:5432" \
  "$image" >/dev/null

for _ in $(seq 1 60); do
  if docker exec "$container" pg_isready -U postgres -d "$database" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$container" pg_isready -U postgres -d "$database" >/dev/null

admin_url="postgresql+psycopg://postgres:${password}@127.0.0.1:${port}/${database}"

cd "$root/apps/api"

KORPUS_DATABASE_URL="$admin_url" "$python_bin" -m alembic -c alembic.ini upgrade head
current="$({ KORPUS_DATABASE_URL="$admin_url" "$python_bin" -m alembic -c alembic.ini current; } 2>&1)"
printf '%s\n' "$current"
grep -q "0020_learning_course_graph" <<<"$current"

width="$(docker exec "$container" psql -U postgres -d "$database" -Atc \
  "SELECT character_maximum_length FROM information_schema.columns WHERE table_schema='public' AND table_name='alembic_version' AND column_name='version_num'")"
[[ "$width" == "128" ]]
printf '%s\n' "alembic-version-width: ${width}"

KORPUS_DATABASE_URL="$admin_url" "$python_bin" -m alembic -c alembic.ini downgrade 0019_rls_binding_backend_identity
current="$({ KORPUS_DATABASE_URL="$admin_url" "$python_bin" -m alembic -c alembic.ini current; } 2>&1)"
printf '%s\n' "$current"
grep -q "0019_rls_binding_backend_identity" <<<"$current"

KORPUS_DATABASE_URL="$admin_url" "$python_bin" -m alembic -c alembic.ini upgrade 0020_learning_course_graph
current="$({ KORPUS_DATABASE_URL="$admin_url" "$python_bin" -m alembic -c alembic.ini current; } 2>&1)"
printf '%s\n' "$current"
grep -q "0020_learning_course_graph" <<<"$current"

KORPUS_TEST_DATABASE_ADMIN_URL="$admin_url" \
PYTHONPATH="$root/apps/api/src" \
"$python_bin" -m pytest tests/test_postgres_learning_course_graph.py --no-cov

printf '%s\n' "learning-postgres-gate: PASS"
