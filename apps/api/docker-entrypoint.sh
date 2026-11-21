#!/usr/bin/env sh
set -eu

read_secret() {
  target="$1"
  file_var="$2"
  eval "path=\${$file_var:-}"
  if [ -n "$path" ]; then
    [ -f "$path" ] && [ -r "$path" ] || { echo "secret file is unreadable: $path" >&2; exit 64; }
    value="$(cat < "$path")" || { echo "secret file is unreadable: $path" >&2; exit 64; }
    [ -n "$value" ] || { echo "secret file is empty: $path" >&2; exit 64; }
    export "$target=$value"
  fi
}

resolve_database_url() {
  read_secret "${1}_PASSWORD" "${1}_PASSWORD_FILE"
  eval "template=\${${1}_URL_TEMPLATE:-}"
  if [ -n "$template" ]; then
    resolved="$(python - "$1" <<'PY'
import os
import sys
from urllib.parse import quote

prefix = sys.argv[1]
template = os.environ[prefix + '_URL_TEMPLATE']
password = os.environ.get(prefix + '_PASSWORD', '')
if not password.strip():
    sys.exit(prefix + '_PASSWORD is required')
if template.count('{password}') != 1:
    sys.exit(prefix + '_URL_TEMPLATE must contain exactly one {password} placeholder')
print(template.replace('{password}', quote(password, safe='')))
PY
)" || exit 64
    export "${1}_URL=$resolved"
  fi
  # Passwords are entrypoint intermediates, not Settings fields. Remove them even
  # when an operator supplied a direct URL instead of a template.
  unset "${1}_PASSWORD"
}

read_secret KORPUS_AUDIT_HMAC_KEY KORPUS_AUDIT_HMAC_KEY_FILE
read_secret KORPUS_JWT_SECRET KORPUS_JWT_SECRET_FILE
read_secret KORPUS_AUDIT_ANCHOR_TOKEN KORPUS_AUDIT_ANCHOR_TOKEN_FILE
read_secret AWS_ACCESS_KEY_ID AWS_ACCESS_KEY_ID_FILE
read_secret AWS_SECRET_ACCESS_KEY AWS_SECRET_ACCESS_KEY_FILE
resolve_database_url KORPUS_DATABASE
resolve_database_url KORPUS_AUTHZ_DATABASE
resolve_database_url KORPUS_REVIEW_DATABASE

exec "$@"
