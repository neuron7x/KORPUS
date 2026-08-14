#!/usr/bin/env sh
set -eu

read_secret() {
  target="$1"
  file_var="$2"
  eval "path=\${$file_var:-}"
  if [ -n "$path" ]; then
    [ -r "$path" ] || { echo "secret file is unreadable: $path" >&2; exit 64; }
    value="$(cat "$path")"
    [ -n "$value" ] || { echo "secret file is empty: $path" >&2; exit 64; }
    export "$target=$value"
  fi
}

build_database_url() {
  target="$1"
  template_var="$2"
  password_var="$3"
  eval "template=\${$template_var:-}"
  eval "password=\${$password_var:-}"
  if [ -n "$template" ]; then
    [ -n "$password" ] || { echo "$password_var is required" >&2; exit 64; }
    value="$(TEMPLATE="$template" PASSWORD="$password" python - <<'PY'
import os
from urllib.parse import quote
print(os.environ['TEMPLATE'].replace('{password}', quote(os.environ['PASSWORD'], safe='')))
PY
)"
    export "$target=$value"
  fi
}

read_secret KORPUS_AUDIT_HMAC_KEY KORPUS_AUDIT_HMAC_KEY_FILE
read_secret KORPUS_JWT_SECRET KORPUS_JWT_SECRET_FILE
read_secret KORPUS_AUDIT_ANCHOR_TOKEN KORPUS_AUDIT_ANCHOR_TOKEN_FILE
read_secret AWS_ACCESS_KEY_ID AWS_ACCESS_KEY_ID_FILE
read_secret AWS_SECRET_ACCESS_KEY AWS_SECRET_ACCESS_KEY_FILE
read_secret KORPUS_DATABASE_PASSWORD KORPUS_DATABASE_PASSWORD_FILE
read_secret KORPUS_REVIEW_DATABASE_PASSWORD KORPUS_REVIEW_DATABASE_PASSWORD_FILE

build_database_url KORPUS_DATABASE_URL KORPUS_DATABASE_URL_TEMPLATE KORPUS_DATABASE_PASSWORD
build_database_url \
  KORPUS_REVIEW_DATABASE_URL \
  KORPUS_REVIEW_DATABASE_URL_TEMPLATE \
  KORPUS_REVIEW_DATABASE_PASSWORD

unset KORPUS_DATABASE_PASSWORD KORPUS_REVIEW_DATABASE_PASSWORD
exec "$@"
