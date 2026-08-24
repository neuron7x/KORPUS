#!/usr/bin/env bash
set -euo pipefail

: "${GCP_PROJECT_ID:?GCP_PROJECT_ID is required}"
: "${GOVERNANCE_BUCKET:?GOVERNANCE_BUCKET is required}"
: "${KORPUS_OIDC_ISSUER:?KORPUS_OIDC_ISSUER is required}"
: "${KORPUS_OIDC_AUDIENCE:?KORPUS_OIDC_AUDIENCE is required}"

bundle_dir="${1:?usage: publish_governance_bundle.sh DIRECTORY [OUTPUT_JSON]}"
output_json="${2:-/tmp/korpus-governance-release.json}"

require() { command -v "$1" >/dev/null 2>&1 || { echo "required command missing: $1" >&2; exit 2; }; }
for cmd in gcloud python3 sha256sum mktemp; do require "$cmd"; done

PYTHONPATH="${PYTHONPATH:-}:apps/api/src" python3 scripts/gcp/verify_governance_bundle.py \
  "$bundle_dir" \
  --oidc-issuer "$KORPUS_OIDC_ISSUER" \
  --oidc-audience "$KORPUS_OIDC_AUDIENCE" \
  --output "$output_json" >/dev/null

release_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["release_id"])' "$output_json")"
[[ "$release_id" =~ ^[0-9a-f]{64}$ ]] || { echo "invalid governance release id" >&2; exit 3; }

mapfile -t files < <(python3 -c 'import json,sys; print("\n".join(json.load(open(sys.argv[1]))["files"].keys()))' "$output_json")
for name in "${files[@]}"; do
  src="${bundle_dir%/}/$name"
  dst="gs://${GOVERNANCE_BUCKET}/releases/${release_id}/${name}"
  # --if-generation-match=0 is the actual create-only predicate; --no-clobber alone
  # may perform a check-then-write sequence and is not our concurrency boundary.
  gcloud storage cp "$src" "$dst" \
    --project="$GCP_PROJECT_ID" \
    --if-generation-match=0 \
    --quiet >/dev/null 2>&1 || {
      # Idempotent retry is acceptable only if the existing immutable object has exactly
      # the locally approved SHA-256. Any mismatch is a release collision and fails shut.
      expected="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["files"][sys.argv[2]])' "$output_json" "$name")"
      actual="$(gcloud storage cat "$dst" --project="$GCP_PROJECT_ID" | sha256sum | awk '{print $1}')"
      [[ "$actual" == "$expected" ]] || { echo "governance object collision: $name" >&2; exit 4; }
    }
  expected="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["files"][sys.argv[2]])' "$output_json" "$name")"
  actual="$(gcloud storage cat "$dst" --project="$GCP_PROJECT_ID" | sha256sum | awk '{print $1}')"
  [[ "$actual" == "$expected" ]] || { echo "remote governance hash mismatch: $name" >&2; exit 5; }
done

printf '%s\n' "$release_id"
