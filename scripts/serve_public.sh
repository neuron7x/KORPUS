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
PY="apps/api/.venv/bin/python"

mkdir -p "$STATE" "$EDGE/html" "$EDGE/tmp/nginx"

# ---------------------------------------------------------------- identity

if [[ ! -f "$STATE/jwt-secret.txt" ]]; then
  "$PY" -c "import secrets;print(secrets.token_urlsafe(48))" > "$STATE/jwt-secret.txt"
  chmod 600 "$STATE/jwt-secret.txt"
fi

export KORPUS_ENVIRONMENT=local
export KORPUS_DATABASE_URL="sqlite:///$ROOT/var/korpus.db"
export KORPUS_OBJECT_ROOT="$ROOT/var/objects"
export KORPUS_AUDIT_HMAC_KEY="${KORPUS_AUDIT_HMAC_KEY:-local-audit-key}"
export KORPUS_AUTH_MODE=jwt
export KORPUS_JWT_SECRET="$(cat "$STATE/jwt-secret.txt")"
export KORPUS_JWT_ISSUER=korpus-public
export KORPUS_JWT_AUDIENCE=korpus
export KORPUS_JWT_MAX_LIFETIME_MINUTES=1440
export KORPUS_BIND_HOST=0.0.0.0
export KORPUS_TRUSTED_HOSTS="*"
export PYTHONPATH="$ROOT/apps/api/src"

# 24h, the policy ceiling. Re-run this script to rotate; the visitor notices nothing
# because the token lives in the edge, not in their browser.
TOKEN="$("$PY" scripts/mint_review_token.py \
  --subject public --minutes 1440 --roles user --clearance public --corpora public)"

# ---------------------------------------------------------------- api

pkill -f "uvicorn korpus.main:app" 2>/dev/null || true
sleep 1
nohup "$PY" -m uvicorn korpus.main:app \
  --host 0.0.0.0 --port "$PORT_API" --log-level warning \
  > "$STATE/api.log" 2>&1 &

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
rm -f "$EDGE/html/console.html" "$EDGE/html/console.js" "$EDGE/html/console_rules.js"
# Told to the page, not inferred by it. The reader drops the login button and the token
# field in this mode: on a public edge the visitor holds no credential, so a control that
# asks for one invites pasting a real token into a page that has no use for it.
printf 'window.KORPUS_CONFIG = Object.freeze({ apiUrl: "/api", publicMode: true });\n' \
  > "$EDGE/html/config.js"
chmod -R a+rX "$EDGE"
chmod a+rwX "$EDGE/tmp" "$EDGE/tmp/nginx"

docker rm -f korpus-public-edge >/dev/null 2>&1 || true
docker run -d --name korpus-public-edge \
  --network host --add-host api:127.0.0.1 \
  -v "$ROOT/$EDGE/nginx.conf:/etc/nginx/nginx.conf:ro" \
  -v "$ROOT/$EDGE/html:/usr/share/nginx/html:ro" \
  --read-only --tmpfs /tmp:size=64m,mode=1777 --tmpfs /var/cache/nginx:size=32m \
  --security-opt no-new-privileges:true \
  --entrypoint sh \
  nginx:1.31.3-alpine@sha256:4a73073bd557c65b759505da037898b61f1be6cbcc3c2c3aeac22d2a470c1752 \
  -c 'mkdir -p /tmp/nginx && exec nginx -g "daemon off;"' >/dev/null

sleep 3
curl -sf "http://127.0.0.1:$PORT_EDGE/healthz" >/dev/null || {
  echo "edge did not start:" >&2; docker logs korpus-public-edge 2>&1 | tail -5 >&2; exit 1; }

echo "api  http://127.0.0.1:$PORT_API"
echo "edge http://127.0.0.1:$PORT_EDGE"
echo "identity: public · roles [user] · clearance public · corpus public · read only"
