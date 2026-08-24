#!/usr/bin/env bash
set -euo pipefail

# Exchange a GitLab job ID token for short-lived Google credentials. No service
# account key is accepted by this path; the GCP provider independently evaluates
# project/ref/environment claims before issuing a token.
required=(
  GCP_ID_TOKEN
  GCP_PROJECT_ID
  GCP_RUNTIME_WIF_PROVIDER
  GCP_RUNTIME_DEPLOYER_SERVICE_ACCOUNT
  CI_PROJECT_ID
  CI_COMMIT_BRANCH
  CI_COMMIT_REF_PROTECTED
  CI_ENVIRONMENT_NAME
  CI_ENVIRONMENT_TIER
)
for name in "${required[@]}"; do
  [[ -n "${!name:-}" ]] || { printf 'missing required variable: %s\n' "$name" >&2; exit 64; }
done

[[ "$CI_PROJECT_ID" == "85043500" ]] || { echo "unexpected GitLab project" >&2; exit 65; }
[[ "$CI_COMMIT_BRANCH" == "main" ]] || { echo "deployment requires main" >&2; exit 66; }
[[ "$CI_COMMIT_REF_PROTECTED" == "true" ]] || { echo "deployment requires protected ref" >&2; exit 67; }
[[ "$CI_ENVIRONMENT_NAME" == "production" ]] || { echo "deployment requires production environment" >&2; exit 68; }
[[ "$CI_ENVIRONMENT_TIER" == "production" ]] || { echo "deployment tier must be production" >&2; exit 69; }

token_file="${CI_PROJECT_DIR}/.gitlab-oidc.jwt"
credential_file="${CI_PROJECT_DIR}/.gcp-wif.json"
umask 077
printf '%s' "$GCP_ID_TOKEN" > "$token_file"

gcloud iam workload-identity-pools create-cred-config "$GCP_RUNTIME_WIF_PROVIDER" \
  --service-account="$GCP_RUNTIME_DEPLOYER_SERVICE_ACCOUNT" \
  --service-account-token-lifetime-seconds=900 \
  --credential-source-file="$token_file" \
  --output-file="$credential_file"

gcloud auth login --brief --cred-file="$credential_file"
gcloud config set project "$GCP_PROJECT_ID" >/dev/null
export GOOGLE_APPLICATION_CREDENTIALS="$credential_file"
printf 'GOOGLE_APPLICATION_CREDENTIALS=%s\n' "$credential_file" > "${CI_PROJECT_DIR}/var/gcp-auth.env"
