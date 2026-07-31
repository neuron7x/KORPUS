#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dir="$root/infra/secrets"
mkdir -p "$dir"
for name in postgres_password minio_password audit_hmac_key jwt_secret; do
  file="$dir/${name}.txt"
  if [[ ! -s "$file" ]]; then
    python3 - <<PY > "$file"
import secrets
print(secrets.token_urlsafe(48))
PY
    chmod 600 "$file"
  fi
done
printf 'local secret files ready in %s\n' "$dir"
