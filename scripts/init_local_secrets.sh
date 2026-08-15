#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dir="$root/infra/secrets"
mkdir -p "$dir"
chmod 700 "$dir"
umask 077

# The files are 0644 and the directory is 0700. That reads backwards for one line and is
# the only combination that works: no other user on this host can traverse into a 0700
# directory, so the file mode protects nothing against them — while a container that
# drops every capability *cannot* read a 0600 file it does not own, not even as root,
# because DAC_OVERRIDE is one of the capabilities dropped.
#
# Executed 2026-08-06: with 0600, minio reported "Unable to validate credentials
# inherited from the secret file(s)" and exited, and `cat /run/secrets/...` inside the
# container answered "Permission denied". Every service in the compose file that reads a
# secret was in that state, which is why the topology had never started.
SECRET_MODE=0644

# The same reasoning for the configuration the containers read. `infra/minio/*.json` and
# `infra/otel-collector.yaml` are not secrets, they are 0660 because that is this tree's
# umask, and a container that dropped DAC_OVERRIDE cannot read them either: minio-init
# died on "open /config/korpus-app-policy.json: permission denied" and the collector on
# "unable to read the file file:/etc/otelcol/config.yaml". Fixed here rather than by hand
# so a fresh clone starts.
chmod 0644 "$root"/infra/minio/*.json "$root"/infra/otel-collector.yaml 2>/dev/null || true
for name in postgres_admin_password postgres_app_password postgres_review_password postgres_identity_password minio_root_password minio_app_secret_key audit_hmac_key jwt_secret metrics_token; do
  file="$dir/${name}.txt"
  if [[ ! -s "$file" ]]; then
    python3 - <<PY > "$file"
import secrets
print(secrets.token_urlsafe(48))
PY
  fi
  chmod "$SECRET_MODE" "$file"
done
if [[ ! -s "$dir/minio_app_access_key.txt" ]]; then
  python3 - <<'PY' > "$dir/minio_app_access_key.txt"
import secrets
print("korpus-" + secrets.token_hex(12))
PY
fi
chmod "$SECRET_MODE" "$dir/minio_app_access_key.txt"

if [[ ! -s "$dir/backup_encryption_key.txt" ]]; then
  python3 - <<'PY2' > "$dir/backup_encryption_key.txt"
import secrets
print(secrets.token_hex(32))
PY2
fi
chmod "$SECRET_MODE" "$dir/backup_encryption_key.txt"
printf 'local secret files ready in %s\n' "$dir"
