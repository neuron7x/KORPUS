#!/usr/bin/env bash
# Другий API — на PostgreSQL і з УВІМКНЕНОЮ семантикою, поруч із чинним лексичним.
#
# Поруч, а не замість: порівнювати дві конфігурації можна лише тоді, коли обидві живі
# одночасно. Замінивши чинну, я мала б два числа з різних моментів і жодного способу
# сказати, що змінилось саме через семантику.
#
# Порт інший, база інша, сховище обʼєктів інше. Спільне лише одне — той самий корпус,
# імпортований із того самого маніфесту, тож різниця у відповідях належить конфігурації.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${KORPUS_SEMANTIC_PORT:-8010}"
# Знято з оточення ОДРАЗУ. Застосунок відкидає будь-яку незнайому змінну KORPUS_*,
# бо друкарська помилка в назві мовчки лишає налаштування на типовому значенні — і
# ця перевірка правильна. Але `KORPUS_SEMANTIC_PORT` адресована СКРИПТУ, не
# застосунку, і дотепер вона текла до нього й валила запуск:
# `KORPUS_SEMANTIC_PORT=8011 scripts/serve_semantic_local.sh` падало з
# «unrecognised KORPUS_* environment variables». Команда була записана в коментарі
# нижче як спосіб підняти контроль — тобто документація описувала запуск, який не
# працює. Змінна споживається тут і далі не йде.
unset KORPUS_SEMANTIC_PORT
IP="$(docker inspect korpus-postgres-1 --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')"
PGPW="$(cat infra/secrets/postgres_admin_password.txt)"
PROFILE="$ROOT/config/governance/public-corpus-v1.json"
SHA="$(python3 -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$PROFILE")"
SECRET_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/korpus-public"

export KORPUS_ENVIRONMENT=local
export KORPUS_DATABASE_URL="postgresql+psycopg://postgres:${PGPW}@${IP}:5432/korpus"
export KORPUS_OBJECT_ROOT="$ROOT/var/runtime/pg-objects"
# Прив'язаний до ПОРТУ, а не до бази. Два API на одному якорі лишають обидва
# неперевірними — «якір попереду голови ланцюга» це те, що верифікатор каже про
# ланцюг, який не рухався, поки рухався чужий. Контрольний прогін піднімає другий
# процес на тій самій базі, тож спільний якір був би вадою за побудовою.
export KORPUS_AUDIT_ANCHOR_PATH="$ROOT/var/runtime/pg-audit-${PORT}.anchor"
# Ключ журналу не вигадується цим скриптом — так само, як у `serve_public.sh`.
#
# Тут стояло `${KORPUS_AUDIT_HMAC_KEY:-local-audit-key}` — той самий вписаний літерал,
# який у публічному скрипті вже прибрали 31.08.2026. Наслідок виміряний 01.09.2026 на
# цій базі: 1925 подій, УСІ під ярликом `legacy-unversioned`, підписані рядком із цього
# файла. Тобто засвідчених подій тут НУЛЬ, і борг РІС із кожним прогоном порівняння,
# доки процес живий. Вісь `audit_attribution` цього не бачила: вона міряє базу обліку.
#
# Контрольна база — не менш доказова за бойову: висновок про пошук, зроблений на ній,
# лягає в реєстр вимог. Журнал, який не можна засвідчити, робить незасвідченим і його.
[[ -s "$SECRET_DIR/audit-key.txt" ]] || {
  echo "немає ключа аудиту: $SECRET_DIR/audit-key.txt — спершу 'make serve-public'" >&2
  exit 69; }
export KORPUS_AUDIT_HMAC_KEY_FILE="$SECRET_DIR/audit-key.txt"
export KORPUS_AUDIT_KEY_ID="${KORPUS_AUDIT_KEY_ID:-korpus-public-2026-08-31}"
# Каблучка несе старий літерал НА ДИСКУ: 1925 подій, підписаних ним, мусять лишатись
# перевірюваними й завтра. Прибрати файл означає зробити історію неперевірюваною рівно
# в мить, коли її полагодили.
[[ -s "$SECRET_DIR/audit-key-serve-semantic-inline.txt" ]] || {
  printf '%s' 'local-audit-key' > "$SECRET_DIR/audit-key-serve-semantic-inline.txt"
  chmod 600 "$SECRET_DIR/audit-key-serve-semantic-inline.txt"; }
export KORPUS_AUDIT_VERIFICATION_KEY_FILES="{\"legacy-unversioned\":\"$SECRET_DIR/audit-key-serve-semantic-inline.txt\"}"
export KORPUS_AUTH_MODE=jwt
export KORPUS_JWT_SECRET="$(cat "$SECRET_DIR/jwt-secret.txt")"
# Перемикається, бо без цього семантику не можна відокремити від бази. Прогін
# 2026-08-30 показав гібридну краще за лексичну за кількістю проходів (92/95 проти
# 89/95) і вдвічі гірше за часткою відповідей — і лише КОНТРОЛЬ на тій самій
# PostgreSQL із KORPUS_SEMANTIC_RETRIEVAL_ENABLED=false довів, що причина в
# семантиці, а не в другій базі: PG-лексична дала 0.835, майже як SQLite-лексична
# 0.861, а гібридна — 0.468.
#   KORPUS_SEMANTIC_RETRIEVAL_ENABLED=false KORPUS_SEMANTIC_PORT=8011 scripts/serve_semantic_local.sh
export KORPUS_SEMANTIC_RETRIEVAL_ENABLED="${KORPUS_SEMANTIC_RETRIEVAL_ENABLED:-true}"
export KORPUS_SEMANTIC_WEIGHT="${KORPUS_SEMANTIC_WEIGHT:-0.20}"
export KORPUS_EMBEDDING_ENDPOINT="http://127.0.0.1:11434/api/embed"
export KORPUS_EMBEDDING_MODEL_ID="qwen3-embedding:0.6b"
export KORPUS_EMBEDDING_DIMENSIONS=1024
export KORPUS_EMBEDDING_TIMEOUT_SECONDS=30
export KORPUS_CORPUS_GOVERNANCE_PROFILE_PATH="$PROFILE"
export KORPUS_CORPUS_GOVERNANCE_PROFILE_SHA256="$SHA"

echo "semantic api  http://127.0.0.1:${PORT}  (postgres, semantic_weight=${KORPUS_SEMANTIC_WEIGHT})" >&2
exec apps/api/.venv/bin/python -m uvicorn korpus.main:create_app --factory \
  --host 127.0.0.1 --port "$PORT" --app-dir apps/api/src
