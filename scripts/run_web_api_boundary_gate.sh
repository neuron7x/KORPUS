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

run_id="act09-$$"
database_mode="${KORPUS_LIVE_DATABASE_MODE:-sqlite}"
case "$database_mode" in sqlite|postgres) ;; *) echo "invalid live database mode" >&2; exit 64;; esac
network="korpus-$run_id-net"
volume="korpus-$run_id-data"
database_container="korpus-$run_id-postgres"
api_container="korpus-$run_id-api"
web_container="korpus-$run_id-web"
api_image="korpus-api-$run_id"
web_image="korpus-web-$run_id"
postgres_image="pgvector/pgvector:0.8.5-pg17-trixie"
host_port="${KORPUS_LIVE_WEB_PORT:-3190}"
ephemeral_secret="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"

cleanup() {
  docker rm -f "$web_container" "$api_container" "$database_container" >/dev/null 2>&1 || true
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
database_url="sqlite:////data/korpus.db"
database_receipt='{"mode":"sqlite"}'
if [[ "$database_mode" == "postgres" ]]; then
  admin_password="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
  app_password="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
  docker run -d --name "$database_container" --network "$network" --network-alias postgres \
    --tmpfs /var/lib/postgresql/data:rw,noexec,nosuid,size=1g \
    -e POSTGRES_DB=korpus -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD="$admin_password" \
    "$postgres_image" >/dev/null
  for _ in $(seq 1 30); do
    if docker exec "$database_container" pg_isready -U postgres -d korpus >/dev/null 2>&1; then break; fi
    sleep 2
  done
  docker exec "$database_container" pg_isready -U postgres -d korpus >/dev/null
  admin_url="postgresql+psycopg://postgres:$admin_password@postgres:5432/korpus"
  database_url="postgresql+psycopg://korpus_app:$app_password@postgres:5432/korpus"
  docker run --rm --network "$network" --entrypoint sh \
    -e KORPUS_DATABASE_URL="$admin_url" \
    -e KORPUS_POSTGRES_APP_ROLE=korpus_app \
    -e KORPUS_POSTGRES_APP_PASSWORD="$app_password" \
    "$api_image" -ec \
    'cd /app/apps/api && python -m alembic -c alembic.ini upgrade head && cd /app && python scripts/prepare_postgres_role.py'
  postgres_digest="$(docker image inspect --format '{{.Id}}' "$postgres_image")"
  database_receipt="$(docker run --rm --network "$network" --entrypoint python \
    -e KORPUS_DATABASE_URL="$admin_url" \
    -e KORPUS_POSTGRES_IMAGE_DIGEST="$postgres_digest" \
    "$api_image" -c \
    'import json,os; from sqlalchemy import create_engine,text; from scripts.alembic_state import database_revisions; e=create_engine(os.environ["KORPUS_DATABASE_URL"]); c=e.connect(); print(json.dumps({"mode":"postgres","image_digest":os.environ["KORPUS_POSTGRES_IMAGE_DIGEST"],"server_version":c.execute(text("SHOW server_version")).scalar_one(),"pgvector_version":c.execute(text("SELECT extversion FROM pg_extension WHERE extname=\047vector\047")).scalar_one(),"alembic_heads":list(database_revisions(os.environ["KORPUS_DATABASE_URL"]))},sort_keys=True)); c.close(); e.dispose()')"
fi
docker run -d --name "$api_container" --network "$network" --network-alias api \
  -v "$volume:/data" \
  -e KORPUS_ENVIRONMENT=test \
  -e KORPUS_DATABASE_URL="$database_url" \
  -e KORPUS_SCHEMA_MODE="$([[ "$database_mode" == "postgres" ]] && echo migrations || echo auto)" \
  -e KORPUS_OBJECT_ROOT=/data/objects \
  -e KORPUS_QUARANTINE_OBJECT_ROOT=/data/quarantine \
  -e KORPUS_AUDIT_ANCHOR_PATH=/data/audit-anchor.json \
  -e KORPUS_AUTH_MODE=jwt \
  -e KORPUS_JWT_SECRET="$ephemeral_secret" \
  -e KORPUS_AUDIT_HMAC_KEY="$ephemeral_secret" \
  "$api_image" >/dev/null
wait_healthy "$api_container"
expected_evidence=""
query_text="перевірити відсутність непідтверджених доказів"
if [[ "$database_mode" == "postgres" ]]; then
  expected_evidence="POSTGRES-BROWSER indexed evidence is visible through the authorized public corpus."
  query_text="POSTGRES-BROWSER indexed evidence authorized public corpus"
  docker exec -i "$api_container" python - <<'PY'
import os
from pathlib import Path
from korpus.domain.models import AccessTier, AuthorityClass, Classification, DocumentRecord, DocumentVersionRecord, EvidenceSpanRecord, Identity, ReviewState
from korpus.infrastructure.repository import SqlRepository

repository = SqlRepository(os.environ["KORPUS_DATABASE_URL"], os.environ["KORPUS_AUDIT_HMAC_KEY"], audit_anchor_path=Path(os.environ["KORPUS_AUDIT_ANCHOR_PATH"]))
repository.initialize(create_schema=False)
actor = Identity(subject="boundary-fixture", roles=frozenset({"admin", "user"}), clearance=AccessTier.PUBLIC, corpora=frozenset({"public"}))
document = DocumentRecord(canonical_title="PostgreSQL browser boundary fixture", corpus_id="public", issuer="KORPUS assurance", jurisdiction="UA", document_type="test-evidence", access_tier=AccessTier.PUBLIC, classification=Classification.PUBLIC)
version = DocumentVersionRecord(document_id=document.id, revision="1", source_hash="d" * 64, object_key="assurance/postgres-browser", mime_type="text/plain", authority=AuthorityClass.OFFICIAL_UA, review_state=ReviewState.APPROVED, is_current=True)
span = EvidenceSpanRecord(version_id=version.id, ordinal=0, text="POSTGRES-BROWSER indexed evidence is visible through the authorized public corpus.")
repository.create_document_bundle(actor, document, version, [span], {"fixture":"postgres-browser-boundary"})
repository.close()
PY
fi
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
KORPUS_LIVE_DATABASE_RECEIPT="$database_receipt" \
KORPUS_LIVE_QUERY="$query_text" \
KORPUS_LIVE_EXPECTED_EVIDENCE="$expected_evidence" \
  npm --prefix apps/web run test:live-boundary
npm --prefix apps/web run validate:live-boundary-report -- \
  ../../var/web-act/web-api-live-boundary.json
