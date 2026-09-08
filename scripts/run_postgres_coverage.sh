#!/usr/bin/env bash
# Покриття на PostgreSQL — другий діалект, який `coverage-union` вимагає і якого локально
# НЕМА ЧИМ виробити.
#
# `run_postgres_suite.sh` іде з `--no-cov` навмисно: він міряє поведінку, не покриття.
# Звіт `var/coverage-postgres.json` виробляв РІВНО ОДИН виконавець — джоб у
# `.gitlab-ci.yml`. Наслідок виміряно 08.09.2026: після будь-якої зміни джерела свіжий
# звіт SQLite порівнювався зі СТАРИМ звітом постгреса, і `merge_dialect_coverage.py`
# чесно відмовляв — «прогони описують різні дерева» (новий модуль є в первинному, нема у
# вторинному). Полагодити це можна було лише конвеєром, тобто ціль була недосяжна доти,
# доки хтось інший не побіжить. Це той самий рід, що предикат, чий виробник стоїть за
# гейтом, який цей предикат гейтить.
#
# Тому виконавець тепер є і тут, і робить ТЕ САМЕ, що джоб: піднімає свою базу, накочує
# міграції, готує ролі й ганяє набір із `--cov`.
#
# Контейнер має ВЛАСНЕ імʼя і порт, відмінні від `run_postgres_suite.sh`: гейт постгреса
# не реентерабельний — два прогони зносять контейнер одне одному, і це вже дало хибний
# FAIL із 35 ERROR (08.09.2026).
#
#   scripts/run_postgres_coverage.sh            # звіт у var/coverage-postgres.json
#   KORPUS_PG_KEEP=1 scripts/run_postgres_coverage.sh   # лишити контейнер
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

out="${KORPUS_COVERAGE_POSTGRES_OUT:-var/coverage-postgres.json}"

# Готова база — і контейнер не потрібен. Це та сама дорога, якою йде джоб CI: там базу
# дає служба конвеєра. Завдяки їй обидва виробники відрізняються РІВНО тим, хто підняв
# постгрес, а не тим, що вони міряють; тест `test_dialect_coverage_producers_agree`
# звіряє прапорці покриття між ними на кожному прогоні.
if [[ -n "${KORPUS_TEST_DATABASE_URL:-}" ]]; then
  exec env PYTHONPATH="$root/apps/api/src" "$python_bin" -m pytest -q -p no:cacheprovider \
    apps/api/tests --cov=apps/api/src/korpus --cov-branch \
    --cov-report="json:${out}" --cov-report= --cov-fail-under=0 "$@"
fi

if ! command -v docker >/dev/null 2>&1; then
  # Відсутній docker — ВІДМОВА, не пропуск: тихо не побігти означало б лишити
  # `coverage-union` при старому звіті й називати це свіжим виміром.
  echo "docker is required for the PostgreSQL coverage report" >&2
  exit 2
fi

image="pgvector/pgvector:0.8.5-pg17-trixie@sha256:69573b32242ca232f65871d4cb916ba7210a372b9bd74068204c1a9a57bada4f"
container="${KORPUS_PG_COVERAGE_CONTAINER:-korpus-pg-coverage}"
# 55433 тримає `run_postgres_suite.sh`, 55434/55435/55437/55440 — довгоживучі
# контейнери власника (rls-probe, rls-probe2, rev-probe, pilot-pg). Перший прогін
# упав саме на «port is already allocated», і впав ТИХО: конвеєр `| tail` зʼїв код
# виходу, а виклик відзвітував нулем.
port="${KORPUS_PG_COVERAGE_PORT:-55444}"
password="cov-postgres-$$"
app_password="cov-app-$$"
authz_password="cov-authz-$$"
review_password="cov-review-$$"
database="korpus_coverage"

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
PYTHONPATH="$root/apps/api/src" "$python_bin" -m pytest -q -p no:cacheprovider apps/api/tests \
  --cov=apps/api/src/korpus --cov-branch \
  --cov-report="json:${out}" --cov-report= --cov-fail-under=0 "$@"
