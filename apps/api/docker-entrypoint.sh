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

read_secret KORPUS_AUDIT_HMAC_KEY KORPUS_AUDIT_HMAC_KEY_FILE
read_secret KORPUS_JWT_SECRET KORPUS_JWT_SECRET_FILE
read_secret KORPUS_AUDIT_ANCHOR_TOKEN KORPUS_AUDIT_ANCHOR_TOKEN_FILE
read_secret AWS_ACCESS_KEY_ID AWS_ACCESS_KEY_ID_FILE
read_secret AWS_SECRET_ACCESS_KEY AWS_SECRET_ACCESS_KEY_FILE
read_secret KORPUS_DATABASE_PASSWORD KORPUS_DATABASE_PASSWORD_FILE

if [ -n "${KORPUS_DATABASE_URL_TEMPLATE:-}" ]; then
  [ -n "${KORPUS_DATABASE_PASSWORD:-}" ] || { echo "database password is required" >&2; exit 64; }
  KORPUS_DATABASE_URL="$(python - <<'PY'
import os
from urllib.parse import quote
print(os.environ['KORPUS_DATABASE_URL_TEMPLATE'].replace('{password}', quote(os.environ['KORPUS_DATABASE_PASSWORD'], safe='')))
PY
)"
  export KORPUS_DATABASE_URL
  # Unset once the URL is built. `main.py` refuses to start on any unrecognised KORPUS_*
  # variable — a typo there silently leaves a setting at its default — and
  # KORPUS_DATABASE_PASSWORD is not a setting, it is an intermediate this script made.
  # Executed 2026-08-06: the API container restart-looped on
  # "unrecognised KORPUS_* environment variables: ['KORPUS_DATABASE_PASSWORD']".
  # Unsetting it also keeps the password out of the process environment, where anything
  # that dumps `os.environ` into a log would carry it.
  unset KORPUS_DATABASE_PASSWORD
fi

exec "$@"
