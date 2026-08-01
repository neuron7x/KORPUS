#!/usr/bin/env bash
set -euo pipefail
umask 077

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
root="$(CDPATH= cd -- "$script_dir/.." && pwd)"
cd "$root"

git diff --quiet && git diff --cached --quiet || {
  echo "live boundary gate requires a clean committed worktree" >&2
  exit 64
}

run_id="act07-$$"
network="korpus-$run_id-net"
volume="korpus-$run_id-data"
api_container="korpus-$run_id-api"
web_container="korpus-$run_id-web"
api_image="korpus-api-$run_id"
web_image="korpus-web-$run_id"
host_port="${KORPUS_LIVE_WEB_PORT:-3190}"
ephemeral_secret="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"

cleanup() {
  docker rm -f "$web_container" "$api_container" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  docker volume rm "$volume" >/dev/null 2>&1 || true
  docker image rm "$web_image" "$api_image" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

wait_healthy() {
  local container="$1"
  local state=""
  for _ in $(seq 1 20); do
    state="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container")"
    if [[ "$state" == "healthy" ]]; then return 0; fi
    if [[ "$state" == "exited" || "$state" == "unhealthy" ]]; then break; fi
    sleep 3
  done
  docker logs --tail 100 "$container" >&2 || true
  echo "$container did not become healthy: $state" >&2
  return 1
}

docker build -f apps/api/Dockerfile -t "$api_image" .
docker build -f apps/web/Dockerfile -t "$web_image" .
docker network create "$network" >/dev/null
docker volume create "$volume" >/dev/null
docker run --rm --user 0:0 -v "$volume:/data" --entrypoint sh "$api_image" \
  -c 'chown -R 10001:10001 /data && chmod 0700 /data'
docker run -d --name "$api_container" --network "$network" --network-alias api \
  -v "$volume:/data" \
  -e KORPUS_ENVIRONMENT=test \
  -e KORPUS_DATABASE_URL=sqlite:////data/korpus.db \
  -e KORPUS_OBJECT_ROOT=/data/objects \
  -e KORPUS_QUARANTINE_OBJECT_ROOT=/data/quarantine \
  -e KORPUS_AUDIT_ANCHOR_PATH=/data/audit-anchor.json \
  -e KORPUS_AUTH_MODE=jwt \
  -e KORPUS_JWT_SECRET="$ephemeral_secret" \
  -e KORPUS_AUDIT_HMAC_KEY="$ephemeral_secret" \
  "$api_image" >/dev/null
wait_healthy "$api_container"
docker run -d --name "$web_container" --network "$network" \
  -p "127.0.0.1:$host_port:8080" "$web_image" >/dev/null
wait_healthy "$web_container"

token="$(docker exec -i "$api_container" python - <<'PY'
from korpus.config import get_settings
from korpus.domain.models import AccessTier, Identity
from korpus.security.auth import issue_token

identity = Identity(
    subject="live-boundary-user",
    roles=frozenset({"user"}),
    clearance=AccessTier.PUBLIC,
    corpora=frozenset({"public"}),
)
print(issue_token(identity, get_settings(), lifetime_minutes=5))
PY
)"
candidate_commit="$(git rev-parse HEAD)"
api_digest="$(docker image inspect --format '{{.Id}}' "$api_image")"
web_digest="$(docker image inspect --format '{{.Id}}' "$web_image")"
KORPUS_LIVE_WEB_URL="http://127.0.0.1:$host_port" \
KORPUS_LIVE_BEARER_TOKEN="$token" \
KORPUS_LIVE_CANDIDATE_COMMIT="$candidate_commit" \
KORPUS_LIVE_API_IMAGE_DIGEST="$api_digest" \
KORPUS_LIVE_WEB_IMAGE_DIGEST="$web_digest" \
  npm --prefix apps/web run test:live-boundary
npm --prefix apps/web run validate:live-boundary-report -- \
  ../../var/web-act/web-api-live-boundary.json
