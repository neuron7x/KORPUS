#!/usr/bin/env bash
# Контрольний сервер на КОПІЇ обслуговуваної бази.
#
# Наслідок зміни в коді відповіді треба виміряти, не чіпаючи те, що обслуговує читача.
# Перезапустити бойовий процес заради виміру означає зробити зміну незворотною ДО того,
# як з'явилось число, а порівняти «до» і «після» на ньому взагалі неможливо: два стани
# ніколи не існують одночасно.
#
# Тут піднімається той самий застосунок із тим самим оточенням, крім двох речей: база —
# копія, зроблена `VACUUM INTO` (узгоджений знімок при WAL, не `cp`), і якір журналу
# свій. Сховище об'єктів спільне й читається лише на читання.
#
# ЖУРНАЛ ПИШЕТЬСЯ. Кожна відповідь додає подію, тож копія на кожен прогін — інакше
# другий прогін міряє базу, яку зрушив перший.
#
#   scripts/serve_control_copy.sh 8021 /tmp/ab/A.db A
#
# Порівняння робиться двома копіями на двох портах: перший процес піднімається ДО
# правки, другий ПІСЛЯ. Код читається при імпорті, тож обидва живуть із одного дерева
# й тримають різні версії — це те, що робить одночасне порівняння можливим.
#
# Виміряно 01.09.2026 саме так: `subject` 0.9451 → 0.9670 при незмінних `boundary`
# 0.95/0.2, `paraphrase` 0.75 і `reference` 92/95 із тими самими трьома провалами.
# Одна вісь із чотирьох — це і є контроль проти підгонки.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${1:?порт}"
DB="${2:?шлях до КОПІЇ бази}"
TAG="${3:-control}"
RUNTIME_RELEASE="${KORPUS_RUNTIME_RELEASE:-corpus-v6-20260807}"
RUNTIME_ROOT="${KORPUS_CONTROL_RUNTIME_ROOT:-$ROOT/var/runtime/$RUNTIME_RELEASE}"
SECRET_DIR="${KORPUS_PUBLIC_SECRET_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/korpus-public}"
PY="apps/api/.venv/bin/python"

# Відмова, а не тихий відкат на бойову базу: `--database` без копії означав би, що
# вимір іде по тому самому файлу, який обслуговує читача, і цього не видно з чисел.
[[ -f "$DB" ]] || { echo "немає копії бази: $DB (зробити: sqlite3 'file:$RUNTIME_ROOT/korpus.db?mode=ro' \"VACUUM INTO '$DB'\")" >&2; exit 66; }
[[ "$(readlink -f "$DB")" != "$(readlink -f "$RUNTIME_ROOT/korpus.db")" ]] || {
  echo "це обслуговувана база, не копія: $DB" >&2; exit 66; }
[[ -s "$SECRET_DIR/jwt-secret.txt" && -s "$SECRET_DIR/audit-key.txt" ]] || {
  echo "немає ключів у $SECRET_DIR — спершу 'make serve-public'" >&2; exit 69; }

export KORPUS_ENVIRONMENT=local
export KORPUS_DATABASE_URL="sqlite:///$(readlink -f "$DB")"
export KORPUS_OBJECT_ROOT="$RUNTIME_ROOT/objects"
export KORPUS_AUDIT_HMAC_KEY_FILE="$SECRET_DIR/audit-key.txt"
export KORPUS_AUDIT_KEY_ID="${KORPUS_AUDIT_KEY_ID:-korpus-public-2026-08-31}"
export KORPUS_AUDIT_VERIFICATION_KEY_FILES="{\"legacy-unversioned\":\"$SECRET_DIR/audit-key-legacy-unversioned.txt\",\"serve-public-inline-2026-08\":\"$SECRET_DIR/audit-key-serve-public-inline.txt\"}"
# Свій якір на пару (порт, база). Спільний файл лишає обидва ланцюги неперевірюваними:
# «якір попереду голови» — це те, що верифікатор каже про ланцюг, який не рухався,
# поки рухався чужий.
export KORPUS_AUDIT_ANCHOR_PATH="$(dirname "$(readlink -f "$DB")")/$TAG.anchor"
export KORPUS_AUTH_MODE=jwt
export KORPUS_JWT_SECRET="$(cat "$SECRET_DIR/jwt-secret.txt")"
export KORPUS_JWT_ISSUER=korpus-public
export KORPUS_JWT_AUDIENCE=korpus
export KORPUS_JWT_MAX_LIFETIME_MINUTES=1440
export KORPUS_BIND_HOST=127.0.0.1
export KORPUS_TRUSTED_HOSTS="localhost,127.0.0.1"
export KORPUS_MODEL_EGRESS_POSTURE=local_only
export KORPUS_MAX_CONCURRENT_ANSWERS=4
export PYTHONPATH="$ROOT/apps/api/src"

echo "контроль  http://127.0.0.1:$PORT  база=$DB  якір=$KORPUS_AUDIT_ANCHOR_PATH" >&2
exec "$PY" -m uvicorn korpus.main:app --host 127.0.0.1 --port "$PORT" --log-level warning
