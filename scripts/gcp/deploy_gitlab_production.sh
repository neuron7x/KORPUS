#!/usr/bin/env bash
set -euo pipefail

required=(
  GCP_PROJECT_ID GCP_TERRAFORM_STATE_BUCKET KORPUS_DOMAIN
  KORPUS_OIDC_ISSUER KORPUS_OIDC_JWKS_URL
  KORPUS_OIDC_AUTHORIZATION_ENDPOINT KORPUS_OIDC_TOKEN_ENDPOINT
  KORPUS_OIDC_CLIENT_ID KORPUS_OIDC_AUDIENCE
  KORPUS_CLAMAV_SOURCE_IMAGE KORPUS_MONITORING_CHANNEL_IDS_JSON
)
for name in "${required[@]}"; do
  [[ -n "${!name:-}" ]] || { printf 'missing required variable: %s\n' "$name" >&2; exit 64; }
done
[[ -f api-image.tar && -f web-image.tar ]] || { echo "verified image artifacts are absent" >&2; exit 65; }
[[ -d config/production/governance ]] || { echo "approved governance bundle is absent" >&2; exit 66; }

region="${GCP_REGION:-europe-central2}"
registry="${region}-docker.pkg.dev/${GCP_PROJECT_ID}/korpus"
mkdir -p reports/production

terraform -chdir=infra/gcp/foundation init -input=false -reconfigure \
  -backend-config="bucket=${GCP_TERRAFORM_STATE_BUCKET}" \
  -backend-config="prefix=korpus/foundation"
export GOVERNANCE_BUCKET
GOVERNANCE_BUCKET="$(terraform -chdir=infra/gcp/foundation output -json buckets | python -c 'import json,sys; print(json.load(sys.stdin)["governance"])')"
export KORPUS_OIDC_ISSUER KORPUS_OIDC_AUDIENCE
governance_release_id="$(scripts/gcp/publish_governance_bundle.sh config/production/governance reports/production/governance.json)"

gcloud auth configure-docker "${region}-docker.pkg.dev" --quiet
docker load --input api-image.tar >/dev/null
docker load --input web-image.tar >/dev/null
api_tag="${registry}/api:${CI_COMMIT_SHA}"
web_tag="${registry}/web:${CI_COMMIT_SHA}"
clamav_tag="${registry}/clamav:${CI_COMMIT_SHA}"
docker tag korpus-api:latest "$api_tag"
docker tag korpus-web:latest "$web_tag"
docker pull "$KORPUS_CLAMAV_SOURCE_IMAGE"
docker tag "$KORPUS_CLAMAV_SOURCE_IMAGE" "$clamav_tag"
docker push "$api_tag"
docker push "$web_tag"
docker push "$clamav_tag"

resolve_image() {
  local tag="$1" digest
  digest="$(gcloud artifacts docker images describe "$tag" --project="$GCP_PROJECT_ID" --format='value(image_summary.digest)')"
  [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "invalid registry digest: $tag" >&2; exit 67; }
  printf '%s@%s' "${tag%:*}" "$digest"
}
api_ref="$(resolve_image "$api_tag")"
web_ref="$(resolve_image "$web_tag")"
clamav_ref="$(resolve_image "$clamav_tag")"
python scripts/gcp/verify_container_vulnerabilities.py --project "$GCP_PROJECT_ID" --image "$api_ref" --output reports/production/api-vulnerabilities.json
python scripts/gcp/verify_container_vulnerabilities.py --project "$GCP_PROJECT_ID" --image "$web_ref" --output reports/production/web-vulnerabilities.json
python scripts/gcp/verify_container_vulnerabilities.py --project "$GCP_PROJECT_ID" --image "$clamav_ref" --output reports/production/clamav-vulnerabilities.json

terraform -chdir=infra/gcp/runtime init -input=false -reconfigure \
  -backend-config="bucket=${GCP_TERRAFORM_STATE_BUCKET}" \
  -backend-config="prefix=korpus/runtime"
python scripts/gcp/validate_migration_compatibility.py | tee reports/production/migration-compatibility.json

governance_value() {
  python -c 'import json,sys; print(json.load(open(sys.argv[1]))["files"][sys.argv[2]])' \
    reports/production/governance.json "$1"
}
export TF_VAR_project_id="$GCP_PROJECT_ID"
export TF_VAR_region="$region"
export TF_VAR_state_bucket="$GCP_TERRAFORM_STATE_BUCKET"
export TF_VAR_domain="$KORPUS_DOMAIN"
export TF_VAR_api_image="$api_ref"
export TF_VAR_web_image="$web_ref"
export TF_VAR_clamav_image="$clamav_ref"
export TF_VAR_oidc_issuer="$KORPUS_OIDC_ISSUER"
export TF_VAR_oidc_jwks_url="$KORPUS_OIDC_JWKS_URL"
export TF_VAR_oidc_authorization_endpoint="$KORPUS_OIDC_AUTHORIZATION_ENDPOINT"
export TF_VAR_oidc_token_endpoint="$KORPUS_OIDC_TOKEN_ENDPOINT"
export TF_VAR_oidc_end_session_endpoint="${KORPUS_OIDC_END_SESSION_ENDPOINT:-}"
export TF_VAR_oidc_client_id="$KORPUS_OIDC_CLIENT_ID"
export TF_VAR_oidc_audience="$KORPUS_OIDC_AUDIENCE"
export TF_VAR_governance_release_id="$governance_release_id"
export TF_VAR_entitlement_profile_sha256="$(governance_value entitlements.json)"
export TF_VAR_source_trust_profile_sha256="$(governance_value source-trust.json)"
export TF_VAR_reviewer_registry_sha256="$(governance_value reviewers.json)"
export TF_VAR_corpus_governance_profile_sha256="$(governance_value corpus-governance.json)"
export TF_VAR_calibration_profile_sha256="$(governance_value calibration.json)"
export TF_VAR_notification_channel_ids="$KORPUS_MONITORING_CHANNEL_IDS_JSON"
export TF_VAR_otlp_endpoint="${KORPUS_OTLP_ENDPOINT:-}"

terraform -chdir=infra/gcp/runtime apply -input=false -auto-approve \
  -target=google_cloud_run_v2_job.migrate \
  -target=google_cloud_run_v2_job.postgres_verify
gcloud run jobs execute korpus-migrate --project="$GCP_PROJECT_ID" --region="$region" --wait
gcloud run jobs execute korpus-postgres-verify --project="$GCP_PROJECT_ID" --region="$region" --wait --format=json \
  > reports/production/postgres-verification.json

capture_traffic() {
  local service="$1" output="$2"
  if gcloud run services describe "$service" --project="$GCP_PROJECT_ID" --region="$region" --format=json > "/tmp/${service}.json" 2>/dev/null; then
    python scripts/gcp/traffic_snapshot.py "/tmp/${service}.json" > "$output"
  else
    : > "$output"
  fi
}
capture_traffic korpus-api /tmp/api-traffic
capture_traffic korpus-web /tmp/web-traffic
previous_api="$(cat /tmp/api-traffic)"
previous_web="$(cat /tmp/web-traffic)"
rollback() {
  python scripts/gcp/rollback_traffic.py --project "$GCP_PROJECT_ID" --region "$region" \
    --api-spec "$previous_api" --web-spec "$previous_web" --output-dir reports/production || true
}
trap rollback ERR

terraform -chdir=infra/gcp/runtime plan -input=false -out=/tmp/runtime.tfplan
terraform -chdir=infra/gcp/runtime apply -input=false -auto-approve /tmp/runtime.tfplan
for service in api web; do
  gcloud run services describe "korpus-${service}" --project="$GCP_PROJECT_ID" --region="$region" --format=json \
    > "reports/production/${service}-candidate-service.json"
  python scripts/gcp/candidate_target.py "reports/production/${service}-candidate-service.json" \
    > "reports/production/${service}-candidate.json"
done
api_revision="$(python scripts/gcp/candidate_target.py reports/production/api-candidate-service.json --field revision)"
api_url="$(python scripts/gcp/candidate_target.py reports/production/api-candidate-service.json --field url)"
web_revision="$(python scripts/gcp/candidate_target.py reports/production/web-candidate-service.json --field revision)"
web_url="$(python scripts/gcp/candidate_target.py reports/production/web-candidate-service.json --field url)"
gcloud run jobs execute korpus-candidate-probe --project="$GCP_PROJECT_ID" --region="$region" --wait \
  --args="--api-url=${api_url},--web-url=${web_url},--attempts=20,--timeout=8" --format=json \
  > reports/production/candidate-probe.json

canary="${KORPUS_CANARY_PERCENT:-5}"
[[ "$canary" =~ ^[0-9]+$ ]] && (( canary >= 1 && canary <= 25 )) || { echo "invalid canary percentage" >&2; exit 68; }
if [[ -n "$previous_api" && -n "$previous_web" ]]; then
  gcloud run services update-traffic korpus-api --project="$GCP_PROJECT_ID" --region="$region" --to-tags="candidate=${canary}"
  gcloud run services update-traffic korpus-web --project="$GCP_PROJECT_ID" --region="$region" --to-tags="candidate=${canary}"
elif [[ -n "$previous_api" || -n "$previous_web" ]]; then
  echo "asymmetric predecessor state" >&2
  exit 69
fi
python scripts/gcp/canary_metrics.py --project "$GCP_PROJECT_ID" --api-revision "$api_revision" \
  --web-revision "$web_revision" --minimum-samples 20 --maximum-error-rate 0.01 \
  --wait-seconds 240 --output reports/production/canary-metrics.json
gcloud run services update-traffic korpus-api --project="$GCP_PROJECT_ID" --region="$region" --to-tags=candidate=100
gcloud run services update-traffic korpus-web --project="$GCP_PROJECT_ID" --region="$region" --to-tags=candidate=100
edge_ip="$(terraform -chdir=infra/gcp/runtime output -raw edge_ip)"
python scripts/gcp/live_smoke.py --domain "$KORPUS_DOMAIN" --expected-ip "$edge_ip" --output reports/production/live-smoke.json
trap - ERR
