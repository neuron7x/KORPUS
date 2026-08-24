#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BOOTSTRAP_DIR="$ROOT/infra/gcp/bootstrap"
REPORT_DIR="$ROOT/reports/production"
API_VERSION="2026-03-10"

: "${GCP_PROJECT_ID:?GCP_PROJECT_ID is required}"
: "${GH_REPO:?GH_REPO must be owner/repository}"
GCP_REGION="${GCP_REGION:-europe-central2}"
GITHUB_DEPLOY_BRANCH="${GITHUB_DEPLOY_BRANCH:-main}"
STATE_BUCKET="${GCP_TERRAFORM_STATE_BUCKET:-${GCP_PROJECT_ID}-korpus-tfstate}"
STATE_PREFIX="korpus/bootstrap"
STATE_RETENTION_SECONDS="${STATE_RETENTION_SECONDS:-2592000}"

fail() { printf 'bootstrap-production: %s\n' "$*" >&2; exit 2; }
need() { command -v "$1" >/dev/null 2>&1 || fail "required command unavailable: $1"; }
for cmd in gcloud gh python3; do need "$cmd"; done
if ! command -v terraform >/dev/null 2>&1 || [[ "$(terraform version -json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("terraform_version", ""))' 2>/dev/null || true)" != "1.15.8" ]]; then
  "$ROOT/scripts/gcp/install_terraform_verified.sh"
fi
need terraform
[[ "$GH_REPO" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || fail "GH_REPO must be owner/repository"
[[ "$GITHUB_DEPLOY_BRANCH" =~ ^[A-Za-z0-9._/-]+$ ]] || fail "invalid GITHUB_DEPLOY_BRANCH"
[[ "$STATE_RETENTION_SECONDS" =~ ^[0-9]+$ ]] && (( STATE_RETENTION_SECONDS >= 604800 )) || fail "STATE_RETENTION_SECONDS must be >= 604800"

mkdir -p "$REPORT_DIR"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

gcloud auth list --filter=status:ACTIVE --format='value(account)' | grep -q . || fail "gcloud has no active authenticated account"
gh auth status >/dev/null 2>&1 || fail "gh is not authenticated"
gcloud projects describe "$GCP_PROJECT_ID" --format='value(projectId)' | grep -Fxq "$GCP_PROJECT_ID" || fail "GCP project is not accessible"
billing_enabled="$(gcloud billing projects describe "$GCP_PROJECT_ID" --format='value(billingEnabled)' 2>/dev/null || true)"
[[ "$billing_enabled" == "True" || "$billing_enabled" == "true" ]] || fail "GCP billing is not enabled or not visible"

repo_json="$tmp/repo.json"
gh api -H "X-GitHub-Api-Version: $API_VERSION" "repos/$GH_REPO" >"$repo_json"
read -r repo_id owner_id default_branch < <(python3 - "$repo_json" <<'PYREPO'
import json,sys
x=json.load(open(sys.argv[1], encoding='utf-8'))
print(str(x['id']), str(x['owner']['id']), x['default_branch'])
PYREPO
)
[[ "$repo_id" =~ ^[0-9]+$ && "$owner_id" =~ ^[0-9]+$ ]] || fail "GitHub immutable IDs unavailable"
gh api -H "X-GitHub-Api-Version: $API_VERSION" "repos/$GH_REPO/branches/$GITHUB_DEPLOY_BRANCH" >/dev/null || fail "deployment branch does not exist"

gcloud services enable serviceusage.googleapis.com storage.googleapis.com --project="$GCP_PROJECT_ID" --quiet
if ! gcloud storage buckets describe "gs://$STATE_BUCKET" --project="$GCP_PROJECT_ID" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://$STATE_BUCKET" \
    --project="$GCP_PROJECT_ID" \
    --location=EU \
    --uniform-bucket-level-access \
    --public-access-prevention \
    --retention-period="${STATE_RETENTION_SECONDS}s" \
    --soft-delete-duration=7d \
    --quiet
fi
gcloud storage buckets update "gs://$STATE_BUCKET" \
  --project="$GCP_PROJECT_ID" \
  --uniform-bucket-level-access \
  --public-access-prevention \
  --versioning \
  --quiet

python3 - "$tmp/bootstrap.tfvars.json" "$GCP_PROJECT_ID" "$GCP_REGION" "$GH_REPO" "$repo_id" "$owner_id" "$GITHUB_DEPLOY_BRANCH" "$STATE_RETENTION_SECONDS" <<'PYVARS'
import json,sys
_,out_path,project,region,repo,repo_id,owner_id,branch,retention=sys.argv
out={"project_id":project,"region":region,"github_repository":repo,"github_repository_id":repo_id,"github_owner_id":owner_id,"github_deploy_branch":branch,"state_retention_seconds":int(retention)}
with open(out_path,'w',encoding='utf-8') as f: json.dump(out,f,sort_keys=True,indent=2)
PYVARS

rm -rf "$BOOTSTRAP_DIR/.terraform"
terraform -chdir="$BOOTSTRAP_DIR" init -input=false -reconfigure \
  -backend-config="bucket=$STATE_BUCKET" \
  -backend-config="prefix=$STATE_PREFIX"
if ! terraform -chdir="$BOOTSTRAP_DIR" state show google_storage_bucket.terraform_state >/dev/null 2>&1; then
  terraform -chdir="$BOOTSTRAP_DIR" import -input=false \
    -var-file="$tmp/bootstrap.tfvars.json" \
    google_storage_bucket.terraform_state "$GCP_PROJECT_ID/$STATE_BUCKET"
fi
terraform -chdir="$BOOTSTRAP_DIR" plan -input=false -lock-timeout=5m \
  -var-file="$tmp/bootstrap.tfvars.json" -out="$tmp/bootstrap.tfplan"
terraform -chdir="$BOOTSTRAP_DIR" apply -input=false -lock-timeout=5m "$tmp/bootstrap.tfplan"

providers_json="$(terraform -chdir="$BOOTSTRAP_DIR" output -json workload_identity_providers)"
accounts_json="$(terraform -chdir="$BOOTSTRAP_DIR" output -json github_deployer_service_accounts)"
actual_bucket="$(terraform -chdir="$BOOTSTRAP_DIR" output -raw state_bucket)"
[[ "$actual_bucket" == "$STATE_BUCKET" ]] || fail "Terraform state bucket output drifted from bootstrap bucket"

read_json_key() {
  python3 -c 'import json,sys; print(json.loads(sys.argv[1])[sys.argv[2]])' "$1" "$2"
}
foundation_wif="$(read_json_key "$providers_json" foundation)"
runtime_wif="$(read_json_key "$providers_json" runtime)"
drill_wif="$(read_json_key "$providers_json" drill)"
foundation_sa="$(read_json_key "$accounts_json" foundation)"
runtime_sa="$(read_json_key "$accounts_json" runtime)"
drill_sa="$(read_json_key "$accounts_json" drill)"

set_repo_var() { gh variable set "$1" --repo "$GH_REPO" --body "$2" >/dev/null; }
set_repo_var GCP_PROJECT_ID "$GCP_PROJECT_ID"
set_repo_var GCP_REGION "$GCP_REGION"
set_repo_var GCP_TERRAFORM_STATE_BUCKET "$STATE_BUCKET"
set_repo_var GCP_FOUNDATION_WIF_PROVIDER "$foundation_wif"
set_repo_var GCP_RUNTIME_WIF_PROVIDER "$runtime_wif"
set_repo_var GCP_DRILL_WIF_PROVIDER "$drill_wif"
set_repo_var GCP_FOUNDATION_DEPLOYER_SERVICE_ACCOUNT "$foundation_sa"
set_repo_var GCP_RUNTIME_DEPLOYER_SERVICE_ACCOUNT "$runtime_sa"
set_repo_var GCP_DRILL_DEPLOYER_SERVICE_ACCOUNT "$drill_sa"
set_repo_var GCP_FOUNDATION_ENABLED "false"
set_repo_var GCP_PRODUCTION_ENABLED "false"

env_payload="$tmp/environment.json"
printf '%s\n' '{"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}}' >"$env_payload"
branch_payload="$tmp/branch-policy.json"
python3 - "$branch_payload" "$GITHUB_DEPLOY_BRANCH" <<'PYBRANCH'
import json,sys
with open(sys.argv[1],'w',encoding='utf-8') as f: json.dump({'name':sys.argv[2],'type':'branch'},f,separators=(',',':'))
PYBRANCH

configure_environment() {
  local environment="$1" policies="$tmp/${environment}-policies.json"
  gh api --method PUT -H "Accept: application/vnd.github+json" -H "X-GitHub-Api-Version: $API_VERSION" \
    "repos/$GH_REPO/environments/$environment" --input "$env_payload" >/dev/null
  gh api -H "X-GitHub-Api-Version: $API_VERSION" \
    "repos/$GH_REPO/environments/$environment/deployment-branch-policies" >"$policies"
  if ! python3 - "$policies" "$GITHUB_DEPLOY_BRANCH" <<'PYCHECK'
import json,sys
x=json.load(open(sys.argv[1],encoding='utf-8')); branch=sys.argv[2]
raise SystemExit(0 if any(p.get('name')==branch and p.get('type')=='branch' for p in x.get('branch_policies',[])) else 1)
PYCHECK
  then
    gh api --method POST -H "Accept: application/vnd.github+json" -H "X-GitHub-Api-Version: $API_VERSION" \
      "repos/$GH_REPO/environments/$environment/deployment-branch-policies" --input "$branch_payload" >/dev/null
  fi
  gh api -H "X-GitHub-Api-Version: $API_VERSION" "repos/$GH_REPO/environments/$environment" >"$tmp/${environment}-final.json"
  gh api -H "X-GitHub-Api-Version: $API_VERSION" \
    "repos/$GH_REPO/environments/$environment/deployment-branch-policies" >"$tmp/${environment}-policies-final.json"
}
configure_environment production
configure_environment production-foundation

python3 - \
  "$tmp/production-final.json" "$tmp/production-policies-final.json" \
  "$tmp/production-foundation-final.json" "$tmp/production-foundation-policies-final.json" \
  "$REPORT_DIR/bootstrap-trust-root.json" \
  "$GCP_PROJECT_ID" "$GCP_REGION" "$GH_REPO" "$repo_id" "$owner_id" "$default_branch" "$GITHUB_DEPLOY_BRANCH" "$STATE_BUCKET" \
  "$foundation_wif" "$runtime_wif" "$drill_wif" "$foundation_sa" "$runtime_sa" "$drill_sa" <<'PYREPORT'
import datetime,json,sys
(_,prod_env_path,prod_pol_path,foundation_env_path,foundation_pol_path,out_path,project,region,repo,repo_id,owner_id,default_branch,branch,bucket,foundation_wif,runtime_wif,drill_wif,foundation_sa,runtime_sa,drill_sa)=sys.argv

def verify(env_path, pol_path):
    env=json.load(open(env_path,encoding='utf-8')); pol=json.load(open(pol_path,encoding='utf-8'))
    dbp=env.get('deployment_branch_policy') or {}
    branch_ok=any(p.get('name')==branch and p.get('type')=='branch' for p in pol.get('branch_policies',[]))
    custom_ok=dbp.get('protected_branches') is False and dbp.get('custom_branch_policies') is True
    if not (branch_ok and custom_ok): raise SystemExit(f'environment branch policy verification failed: {env_path}')
    return {'custom_branch_policies':True,'branch_policy_verified':branch,'required_reviewer_claim':'NOT_ASSERTED_SOLO_MODE'}

out={
  'schema_version':2,
  'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
  'status':'PASS',
  'project_id':project,
  'billing_enabled':True,
  'region':region,
  'github_repository':repo,
  'github_repository_id':repo_id,
  'github_owner_id':owner_id,
  'github_default_branch':default_branch,
  'deployment_branch':branch,
  'state_bucket':bucket,
  'identity_planes':{
    'foundation':{'workload_identity_provider':foundation_wif,'service_account':foundation_sa,'workflow_ref':f'{repo}/.github/workflows/gcp-foundation.yml@refs/heads/{branch}'},
    'runtime':{'workload_identity_provider':runtime_wif,'service_account':runtime_sa,'workflow_ref':f'{repo}/.github/workflows/gcp-production.yml@refs/heads/{branch}'},
    'drill':{'workload_identity_provider':drill_wif,'service_account':drill_sa,'workflow_ref':f'{repo}/.github/workflows/gcp-drill.yml@refs/heads/{branch}'},
  },
  'environments':{
    'production':verify(prod_env_path,prod_pol_path),
    'production-foundation':verify(foundation_env_path,foundation_pol_path),
  },
  'foundation_enabled':False,
  'production_enabled':False,
}
with open(out_path,'w',encoding='utf-8') as f: json.dump(out,f,sort_keys=True,indent=2); f.write('\n')
PYREPORT
printf 'PASS: workflow-isolated trust root verified; foundation and production remain disabled until explicit enablement.\n'
printf 'Evidence: %s\n' "$REPORT_DIR/bootstrap-trust-root.json"
