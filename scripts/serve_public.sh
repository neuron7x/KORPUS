#!/usr/bin/env bash
# Bring up the public deployment: API, authenticating edge, tunnel.
#
# The visitor holds nothing. A read-only identity is minted here, injected by the edge on
# every /api/ request, and rotated by re-running this script — a browser cannot leak a
# token it was never given, and nobody has to be told how to authenticate.
#
# What that identity can do is decided by the API, not by the interface: roles [user],
# clearance public, corpus public. It cannot ingest, review, approve, rescind or read the
# audit chain. The consoles are not served at all.
#
# Everything published this way is public. That is the point and it is a decision, not a
# default: the corpus behind it must contain only material somebody has agreed to publish.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

STATE="var/public"
EDGE="$STATE/edge"
PORT_API="${KORPUS_PUBLIC_API_PORT:-8000}"
PORT_EDGE="${KORPUS_PUBLIC_EDGE_PORT:-8081}"
EDGE_ONLY="${KORPUS_PUBLIC_EDGE_ONLY:-false}"
PY="apps/api/.venv/bin/python"
RUNTIME_RELEASE="${KORPUS_RUNTIME_RELEASE:-corpus-v6-20260807}"
RUNTIME_ROOT="${KORPUS_PUBLIC_RUNTIME_ROOT:-$ROOT/var/runtime/$RUNTIME_RELEASE}"

# Secrets live OUTSIDE the repository tree by default. The JWT secret used to be written
# to var/public/ inside the checkout, so a naive `zip -r korpus .` or an rsync of the
# working directory carried the signing key with the code. Runtime files (logs, the
# rendered nginx.conf) stay in var/; only the secret moves to XDG state, and the operator
# can pin it with KORPUS_PUBLIC_SECRET_DIR.
SECRET_DIR="${KORPUS_PUBLIC_SECRET_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/korpus-public}"

# Preflight: fail early with a fixable message rather than three steps in with a stack
# trace. A fresh clone has neither the venv nor the web build, and the failure otherwise
# surfaces as an obscure "no such file" from deep inside a subprocess.
[[ -x "$PY" ]] || { echo "run 'make api-install' first: $PY is missing" >&2; exit 69; }
command -v docker >/dev/null || { echo "docker is required for the edge; install it" >&2; exit 69; }
EDGE_IMAGE="korpus-public-edge-runtime:nginx-1.31.3-alpine-r1"

mkdir -p "$STATE" "$EDGE/html" "$EDGE/tmp/nginx" "$SECRET_DIR"
chmod 700 "$SECRET_DIR"

# ---------------------------------------------------------------- identity

if [[ ! -f "$SECRET_DIR/jwt-secret.txt" ]]; then
  "$PY" -c "import secrets;print(secrets.token_urlsafe(48))" > "$SECRET_DIR/jwt-secret.txt"
  chmod 600 "$SECRET_DIR/jwt-secret.txt"
fi
echo "secrets: $SECRET_DIR (outside the repository; do not copy into a release)" >&2

# One-time migration off the old in-tree location, so an existing deployment keeps its
# signing key rather than minting a new one and invalidating live sessions.
if [[ -f "$STATE/jwt-secret.txt" && ! -s "$SECRET_DIR/jwt-secret.txt" ]]; then
  mv "$STATE/jwt-secret.txt" "$SECRET_DIR/jwt-secret.txt"
fi
rm -f "$STATE/jwt-secret.txt"

export KORPUS_ENVIRONMENT=local
# The imported Drive corpus, not the bootstrap fixture. SQLite is in WAL mode here, so
# the reader serves while `import_corpus.py` is still writing: the base grows under a
# running site instead of the site waiting hours for the last document.
export KORPUS_DATABASE_URL="${KORPUS_DATABASE_URL:-sqlite:///$RUNTIME_ROOT/korpus.db}"
export KORPUS_OBJECT_ROOT="${KORPUS_OBJECT_ROOT:-$RUNTIME_ROOT/objects}"
export KORPUS_AUDIT_HMAC_KEY="${KORPUS_AUDIT_HMAC_KEY:-local-audit-key}"
# Beside the database it belongs to. The anchor is an external record of where a chain
# has got to; two databases sharing one file leaves both unverifiable — "the anchor is
# ahead of the database head" is what a verifier says about a chain that never moved
# while somebody else's did. Found 2026-08-07: the demo corpus and the imported one had
# been pointing at the same var/audit-anchor.json since the first deployment.
export KORPUS_AUDIT_ANCHOR_PATH="${KORPUS_AUDIT_ANCHOR_PATH:-$RUNTIME_ROOT/audit.anchor}"
export KORPUS_AUTH_MODE=jwt
export KORPUS_JWT_SECRET="$(cat "$SECRET_DIR/jwt-secret.txt")"
export KORPUS_JWT_ISSUER=korpus-public
export KORPUS_JWT_AUDIENCE=korpus
export KORPUS_JWT_MAX_LIFETIME_MINUTES=1440
export KORPUS_BIND_HOST=127.0.0.1
export KORPUS_TRUSTED_HOSTS="localhost,127.0.0.1"
# Admission control is per *identity*, and on this edge there is one: every visitor
# arrives as `public`. The limit is process-local: four per each of two Uvicorn workers
# is an aggregate budget of eight, aligned with the edge.
export KORPUS_MAX_CONCURRENT_ANSWERS="${KORPUS_MAX_CONCURRENT_ANSWERS:-4}"
# Публічна поверхня не має виходу назовні, і сказати це треба ТУТ, а не тоді, коли
# хтось вмикатиме композитор. Виміряно 31.08.2026: `/v1/inference/status` на живому
# розгортанні оголошував `egress_posture=external_allowed` — типове значення, яке
# ніхто не помічав рівно тому, що воно інертне, поки інференс вимкнений. Шар стелі
# матеріалу (`ModelEgressPolicy.max_external_tier`) працює, але він відповідає на
# питання «скільки можна випустити», а не «чи взагалі є куди». Для поверхні, що
# дивиться в інтернет, друге питання має відповідь «немає», і вмикання інференсу не
# повинно мовчки її змінювати: `local_only` лишає лише loopback і приватні адреси.
export KORPUS_MODEL_EGRESS_POSTURE="${KORPUS_MODEL_EGRESS_POSTURE:-local_only}"
export PYTHONPATH="$ROOT/apps/api/src"

# 24h, the policy ceiling. Re-run this script to rotate; the visitor notices nothing
# because the token lives in the edge, not in their browser.
TOKEN="$("$PY" scripts/mint_review_token.py \
  --subject public --minutes 1440 --roles user --clearance public --corpora public)"

# ---------------------------------------------------------------- api

# Migrations before the API, always. `schema_mode=auto` creates missing *tables* and
# never alters an existing one, so a corpus built before a column was added starts
# cleanly and fails on the first write that needs it — found on 2026-08-07 by restoring
# the shipped bundle: the corpus answered questions and could not append to the audit
# chain, because the backup predated migration 0011.
if [[ "$EDGE_ONLY" != "true" ]]; then
  (
    cd "$ROOT/apps/api"
    KORPUS_DATABASE_URL="$KORPUS_DATABASE_URL" PYTHONPATH="$ROOT/apps/api/src" \
      "$ROOT/$PY" -m alembic -c alembic.ini upgrade head
  ) >> "$STATE/api.log" 2>&1 || {
    echo "migrations failed; see $STATE/api.log" >&2; exit 1; }

# Refuse to publish a demo, partial or corrupted corpus by accident. This verifies the
# complete reference set and every referenced source object before the network edge is
# opened; a previous deployment silently selected the empty var/korpus-ml.db instead.
  "$PY" scripts/audit_runtime_corpus.py \
    --database "${KORPUS_DATABASE_URL#sqlite:///}" \
    --object-root "$KORPUS_OBJECT_ROOT" \
    --out "$STATE/runtime-corpus-audit.json" >/dev/null || {
    echo "runtime corpus admission failed; see $STATE/runtime-corpus-audit.json" >&2; exit 1; }

  pkill -f "uvicorn korpus.main:app" 2>/dev/null || true
  sleep 1
# Two processes preserve parallel answers without letting the API claim half of this
# 16-thread laptop before Codex, the worker, or the browser gets scheduled.
WORKERS="${KORPUS_PUBLIC_WORKERS:-2}"
# Deployment-only controls are not application settings. If the caller supplied this
# one through the environment it retained Bash's export attribute and leaked into each
# Uvicorn worker, where strict KORPUS_* validation correctly rejected it as unknown.
  unset KORPUS_PUBLIC_WORKERS
  unset KORPUS_RUNTIME_RELEASE KORPUS_PUBLIC_RUNTIME_ROOT KORPUS_PUBLIC_EDGE_ONLY
  nohup "$PY" -m uvicorn korpus.main:app \
    --host 127.0.0.1 --port "$PORT_API" --log-level warning --workers "$WORKERS" \
    > "$STATE/api.log" 2>&1 &
fi

for _ in $(seq 1 30); do
  curl -sf "http://127.0.0.1:$PORT_API/health" >/dev/null 2>&1 && break
  sleep 1
done
curl -sf "http://127.0.0.1:$PORT_API/health" >/dev/null || { echo "API did not start; see $STATE/api.log" >&2; exit 1; }

# ---------------------------------------------------------------- edge

# Staged rather than mounted from the tree: the container runs as a different user, and
# loosening the repository's own permissions to accommodate it would be a real change to
# this tree's posture for the sake of a demonstration.
"$PY" - "$TOKEN" <<'PYEOF'
import sys
from pathlib import Path

token = sys.argv[1]
config = Path("deploy/public/nginx.conf").read_text(encoding="utf-8")
# Substituted here rather than by nginx: stock nginx has no environment interpolation in
# a directive value, and `envsubst` on the whole file would eat every `$host` and
# `$binary_remote_addr` in it.
Path("var/public/edge/nginx.conf").write_text(
    config.replace("${KORPUS_PUBLIC_TOKEN}", token), encoding="utf-8"
)
PYEOF
chmod a+r "$EDGE/nginx.conf"

npm --prefix apps/web run build --silent >/dev/null
rm -rf "$EDGE/html" && mkdir -p "$EDGE/html"
cp -r apps/web/dist/. "$EDGE/html/"
# Not served, and not staged either: a file that is not there cannot be served by a
# misconfiguration later.
#
# Перелік тут стояв уписаним — `console.html console.js console_rules.js` — і був
# третьою копією одного правила: те саме тримали `deploy_public_web.py` і
# `deploy/public/nginx.conf`. Усі три говорили «консоль», усі три перелічували три
# імені, і всі три відстали разом: 31.08.2026 у публічному edge лежали й віддавалися
# `console.css`, `console_accounts.js`, `console_mutations.js`, `console_readonly.js`.
# Тепер перелік один і похідний — закриття `console.html` мінус закриття `index.html`.
OPERATOR_ONLY="$(mktemp)"
# Перелік рахується з ДЖЕРЕЛА (`apps/web/public`), а прибирається зі зібраного:
# `dist` — копія джерела, але саме джерело лежить у git, і саме там правило можна
# перевірити тестом без попереднього складання.
"$PY" scripts/deploy_public_web.py --print-operator-only apps/web/public > "$OPERATOR_ONLY"
[[ -s "$OPERATOR_ONLY" ]] || { echo "порожня операторська поверхня — правило зламане" >&2; exit 70; }
while IFS= read -r operator_file; do
  rm -f "$EDGE/html/$operator_file"
done < "$OPERATOR_ONLY"
rm -f "$OPERATOR_ONLY"
# Told to the page, not inferred by it. The reader drops the login button and the token
# field in this mode: on a public edge the visitor holds no credential, so a control that
# asks for one invites pasting a real token into a page that has no use for it.
printf 'window.KORPUS_CONFIG = Object.freeze({ apiUrl: "/api", publicMode: true });\n' \
  > "$EDGE/html/config.js"
chmod -R a+rX "$EDGE"
chmod a+rwX "$EDGE/tmp" "$EDGE/tmp/nginx"

docker build --quiet --file deploy/public/Dockerfile.edge --tag "$EDGE_IMAGE" . >/dev/null
docker rm -f korpus-public-edge >/dev/null 2>&1 || true
docker run -d --name korpus-public-edge --restart unless-stopped \
  --network host --add-host api:127.0.0.1 \
  -v "$ROOT/$EDGE/nginx.conf:/etc/nginx/nginx.conf:ro" \
  -v "$ROOT/$EDGE/html:/usr/share/nginx/html:ro" \
  --read-only --tmpfs /tmp:size=64m,mode=1777 --tmpfs /var/cache/nginx:size=32m \
  --security-opt no-new-privileges:true \
  --entrypoint sh \
  "$EDGE_IMAGE" \
  -c 'mkdir -p /tmp/nginx && exec nginx -g "daemon off;"' >/dev/null

sleep 3
curl -sf "http://127.0.0.1:$PORT_EDGE/healthz" >/dev/null || {
  echo "edge did not start:" >&2; docker logs korpus-public-edge 2>&1 | tail -5 >&2; exit 1; }

echo "api  http://127.0.0.1:$PORT_API"
echo "edge http://127.0.0.1:$PORT_EDGE"
echo "identity: public · roles [user] · clearance public · corpus public · read only"
