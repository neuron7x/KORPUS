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
IP="$(docker inspect korpus-postgres-1 --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')"
PGPW="$(cat infra/secrets/postgres_admin_password.txt)"
PROFILE="$ROOT/config/governance/public-corpus-v1.json"
SHA="$(python3 -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$PROFILE")"
SECRET_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/korpus-public"

export KORPUS_ENVIRONMENT=local
export KORPUS_DATABASE_URL="postgresql+psycopg://postgres:${PGPW}@${IP}:5432/korpus"
export KORPUS_OBJECT_ROOT="$ROOT/var/runtime/pg-objects"
export KORPUS_AUDIT_ANCHOR_PATH="$ROOT/var/runtime/pg-audit.anchor"
export KORPUS_AUDIT_HMAC_KEY="${KORPUS_AUDIT_HMAC_KEY:-local-audit-key}"
export KORPUS_AUTH_MODE=jwt
export KORPUS_JWT_SECRET="$(cat "$SECRET_DIR/jwt-secret.txt")"
export KORPUS_SEMANTIC_RETRIEVAL_ENABLED=true
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
