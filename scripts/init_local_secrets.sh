#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dir="$root/infra/secrets"
mkdir -p "$dir"
umask 077
for name in postgres_admin_password postgres_app_password minio_root_password minio_app_secret_key audit_hmac_key jwt_secret metrics_token; do
  file="$dir/${name}.txt"
  if [[ ! -s "$file" ]]; then
    python3 - <<PY > "$file"
import secrets
print(secrets.token_urlsafe(48))
PY
  fi
  chmod 600 "$file"
done
if [[ ! -s "$dir/minio_app_access_key.txt" ]]; then
  python3 - <<'PY' > "$dir/minio_app_access_key.txt"
import secrets
print("korpus-" + secrets.token_hex(12))
PY
fi
chmod 600 "$dir/minio_app_access_key.txt"

if [[ ! -s "$dir/backup_encryption_key.txt" ]]; then
  python3 - <<'PY2' > "$dir/backup_encryption_key.txt"
import secrets
print(secrets.token_hex(32))
PY2
fi
chmod 600 "$dir/backup_encryption_key.txt"
printf 'local secret files ready in %s\n' "$dir"
