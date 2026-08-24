#!/usr/bin/env bash
set -euo pipefail

: "${GCP_PROJECT_ID:?GCP_PROJECT_ID is required}"
: "${CLOUD_SQL_INSTANCE:?CLOUD_SQL_INSTANCE is required}"
: "${KORPUS_OIDC_CLIENT_SECRET:?KORPUS_OIDC_CLIENT_SECRET is required}"

require() { command -v "$1" >/dev/null 2>&1 || { echo "required command missing: $1" >&2; exit 2; }; }
for cmd in gcloud curl python3 openssl mktemp; do require "$cmd"; done

generate_secret() {
  # Hex is deliberately URL-safe and shell-safe; 32 random bytes = 256 bits.
  openssl rand -hex 32
}

latest_enabled_version() {
  local secret="$1"
  gcloud secrets versions list "$secret" \
    --project="$GCP_PROJECT_ID" \
    --filter='state=ENABLED' \
    --sort-by='~createTime' \
    --limit=1 \
    --format='value(name)' 2>/dev/null || true
}

ensure_generated_secret() {
  local secret="$1"
  if [[ -z "$(latest_enabled_version "$secret")" ]]; then
    local value
    value="$(generate_secret)"
    printf '%s' "$value" | gcloud secrets versions add "$secret" \
      --project="$GCP_PROJECT_ID" --data-file=- --quiet >/dev/null
    unset value
    echo "seeded $secret" >&2
  fi
}

for secret in \
  korpus-db-admin-password \
  korpus-db-app-password \
  korpus-audit-hmac-key \
  korpus-browser-session-key \
  korpus-metrics-token; do
  ensure_generated_secret "$secret"
done

if [[ -z "$(latest_enabled_version korpus-oidc-client-secret)" ]]; then
  printf '%s' "$KORPUS_OIDC_CLIENT_SECRET" | gcloud secrets versions add korpus-oidc-client-secret \
    --project="$GCP_PROJECT_ID" --data-file=- --quiet >/dev/null
  echo "seeded korpus-oidc-client-secret" >&2
fi

# Cloud SQL creates postgres without a password. Set it using the Admin REST API so
# the password is never placed in argv or Terraform state.
admin_password="$(gcloud secrets versions access latest \
  --project="$GCP_PROJECT_ID" --secret=korpus-db-admin-password)"
[[ -n "$admin_password" ]] || { echo "empty database admin secret" >&2; exit 4; }

tmp="$(mktemp -d)"
cleanup() { rm -rf "$tmp"; unset admin_password; }
trap cleanup EXIT
chmod 700 "$tmp"
PASSWORD="$admin_password" python3 - "$tmp/user.json" <<'PY'
import json, os, pathlib, sys
path = pathlib.Path(sys.argv[1])
path.write_text(json.dumps({"password": os.environ["PASSWORD"]}), encoding="utf-8")
path.chmod(0o600)
PY

access_token="$(gcloud auth print-access-token)"
response="$tmp/response.json"
encoded_project="$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=""))' "$GCP_PROJECT_ID")"
encoded_instance="$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=""))' "$CLOUD_SQL_INSTANCE")"
url="https://sqladmin.googleapis.com/v1/projects/${encoded_project}/instances/${encoded_instance}/users?name=postgres"
http_code="$(curl --proto '=https' --tlsv1.2 --fail-with-body --silent --show-error \
  --output "$response" --write-out '%{http_code}' \
  --request PUT \
  --header "Authorization: Bearer ${access_token}" \
  --header 'Content-Type: application/json' \
  --data-binary "@$tmp/user.json" \
  "$url")"
[[ "$http_code" == "200" ]] || { cat "$response" >&2; exit 5; }

operation="$(python3 - "$response" <<'PY'
import json, pathlib, sys
obj=json.loads(pathlib.Path(sys.argv[1]).read_text())
name=obj.get("name")
if not isinstance(name,str) or not name:
    raise SystemExit("Cloud SQL users.update returned no operation name")
print(name)
PY
)"
gcloud sql operations wait "$operation" --project="$GCP_PROJECT_ID" --timeout=600 --quiet >/dev/null

echo "runtime secrets are present and postgres admin authentication is synchronized" >&2
