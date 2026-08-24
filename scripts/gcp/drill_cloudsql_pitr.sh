#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

: "${GCP_PROJECT_ID:?GCP_PROJECT_ID is required}"
: "${GCP_REGION:?GCP_REGION is required}"
SOURCE_INSTANCE="${KORPUS_SQL_INSTANCE:-korpus-prod-postgres}"
REPORT_DIR="${KORPUS_DR_REPORT_DIR:-reports/production/dr}"
RUN_TOKEN="${GITHUB_RUN_ID:-manual}-$(date -u +%Y%m%d%H%M%S)"
RUN_TOKEN="$(printf '%s' "$RUN_TOKEN" | tr -cd 'a-zA-Z0-9-' | tr '[:upper:]' '[:lower:]' | cut -c1-32)"
CLONE_INSTANCE="korpus-dr-${RUN_TOKEN}"
VERIFY_JOB="korpus-dr-verify-${RUN_TOKEN}"
MIGRATOR_SA="korpus-migrator@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
API_SERVICE="${KORPUS_API_SERVICE:-korpus-api}"

fail() { printf 'cloudsql-pitr-drill: %s\n' "$*" >&2; exit 2; }
need() { command -v "$1" >/dev/null 2>&1 || fail "required command unavailable: $1"; }
for cmd in gcloud curl python3; do need "$cmd"; done
mkdir -p "$REPORT_DIR"
tmp="$(mktemp -d)"
clone_created=0
job_created=0
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

cleanup() {
  set +e
  if (( job_created )); then
    gcloud run jobs delete "$VERIFY_JOB" --project="$GCP_PROJECT_ID" --region="$GCP_REGION" --quiet >/dev/null 2>&1
  fi
  if (( clone_created )); then
    gcloud sql instances delete "$CLONE_INSTANCE" --project="$GCP_PROJECT_ID" --quiet >/dev/null 2>&1
  fi
  rm -rf "$tmp"
}
trap cleanup EXIT

gcloud auth list --filter=status:ACTIVE --format='value(account)' | grep -q . || fail "no active gcloud identity"
source_json="$tmp/source.json"
gcloud sql instances describe "$SOURCE_INSTANCE" --project="$GCP_PROJECT_ID" --format=json >"$source_json"
python3 - "$source_json" "$GCP_REGION" <<'PY'
import json,sys
x=json.load(open(sys.argv[1],encoding='utf-8')); region=sys.argv[2]
assert x.get('state') == 'RUNNABLE', f"source state={x.get('state')}"
assert x.get('region') == region, f"source region={x.get('region')} expected={region}"
assert x.get('databaseVersion') == 'POSTGRES_17', x.get('databaseVersion')
bc=(x.get('settings') or {}).get('backupConfiguration') or {}
assert bc.get('pointInTimeRecoveryEnabled') is True, 'PITR disabled'
PY

token="$(gcloud auth print-access-token)"
recovery_json="$tmp/recovery.json"
curl --fail --silent --show-error \
  -H "Authorization: Bearer $token" \
  "https://sqladmin.googleapis.com/sql/v1beta4/projects/${GCP_PROJECT_ID}/instances/${SOURCE_INSTANCE}/getLatestRecoveryTime" \
  >"$recovery_json"
read -r earliest latest < <(python3 - "$recovery_json" <<'PY'
import json,sys
x=json.load(open(sys.argv[1],encoding='utf-8'))
e=x.get('earliestRecoveryTime'); l=x.get('latestRecoveryTime')
if not e or not l: raise SystemExit('PITR recovery window unavailable')
print(e,l)
PY
)

# PITR always creates a new instance, so production data is never overwritten by the drill.
gcloud sql instances clone "$SOURCE_INSTANCE" "$CLONE_INSTANCE" \
  --project="$GCP_PROJECT_ID" \
  --point-in-time="$latest" \
  --quiet
clone_created=1

clone_json="$tmp/clone.json"
gcloud sql instances describe "$CLONE_INSTANCE" --project="$GCP_PROJECT_ID" --format=json >"$clone_json"
connection_name="$(python3 - "$clone_json" "$GCP_REGION" <<'PY'
import json,sys
x=json.load(open(sys.argv[1],encoding='utf-8')); region=sys.argv[2]
assert x.get('state') == 'RUNNABLE', f"clone state={x.get('state')}"
assert x.get('region') == region, f"clone region={x.get('region')} expected={region}"
assert x.get('databaseVersion') == 'POSTGRES_17', x.get('databaseVersion')
name=x.get('connectionName')
if not name: raise SystemExit('clone connectionName unavailable')
print(name)
PY
)"

api_image="$(gcloud run services describe "$API_SERVICE" --project="$GCP_PROJECT_ID" --region="$GCP_REGION" --format='value(spec.template.spec.containers[0].image)' 2>/dev/null || true)"
[[ "$api_image" =~ @sha256:[0-9a-f]{64}$ ]] || fail "deployed API image is not digest pinned: ${api_image:-missing}"

admin_template="postgresql+psycopg://postgres:{password}@/korpus?host=/cloudsql/${connection_name}"
gcloud run jobs deploy "$VERIFY_JOB" \
  --project="$GCP_PROJECT_ID" --region="$GCP_REGION" \
  --image="$api_image" \
  --service-account="$MIGRATOR_SA" \
  --set-cloudsql-instances="$connection_name" \
  --set-secrets="/secrets/db-admin/password=korpus-db-admin-password:latest,/secrets/db-app/password=korpus-db-app-password:latest" \
  --set-env-vars="KORPUS_DATABASE_URL_TEMPLATE=${admin_template},KORPUS_DATABASE_PASSWORD_FILE=/secrets/db-admin/password,KORPUS_POSTGRES_APP_ROLE=korpus_app,KORPUS_POSTGRES_APP_PASSWORD_FILE=/secrets/db-app/password" \
  --command=/usr/local/bin/korpus-entrypoint \
  --args=python,scripts/gcp/verify_live_postgres.py,--output,- \
  --tasks=1 --max-retries=0 --task-timeout=300s --cpu=1 --memory=512Mi \
  --quiet
job_created=1

gcloud run jobs execute "$VERIFY_JOB" \
  --project="$GCP_PROJECT_ID" --region="$GCP_REGION" --wait --format=json \
  >"$tmp/execution.json"
gcloud run jobs executions describe-latest \
  --job="$VERIFY_JOB" --project="$GCP_PROJECT_ID" --region="$GCP_REGION" --format=json \
  >"$tmp/execution-latest.json"

finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
report="$REPORT_DIR/cloudsql-pitr-${RUN_TOKEN}.json"
python3 - "$source_json" "$clone_json" "$recovery_json" "$tmp/execution-latest.json" "$report" \
  "$started_at" "$finished_at" "$SOURCE_INSTANCE" "$CLONE_INSTANCE" "$VERIFY_JOB" "$api_image" <<'PY'
import json,sys
(_,source_path,clone_path,recovery_path,execution_path,out_path,started,finished,source_name,clone_name,job_name,image)=sys.argv
source=json.load(open(source_path,encoding='utf-8'))
clone=json.load(open(clone_path,encoding='utf-8'))
recovery=json.load(open(recovery_path,encoding='utf-8'))
execution=json.load(open(execution_path,encoding='utf-8'))
conditions=(execution.get('status') or {}).get('conditions') or []
terminal=[c for c in conditions if c.get('type') in ('Completed','Ready')]
execution_ok=any(c.get('state')=='CONDITION_SUCCEEDED' or c.get('status')=='True' for c in terminal)
if not execution_ok:
    raise SystemExit('DR verification Cloud Run execution did not report success')
out={
  'schema_version':1,
  'status':'PASS',
  'started_at':started,
  'finished_at':finished,
  'source_instance':source_name,
  'source_database_version':source.get('databaseVersion'),
  'source_region':source.get('region'),
  'pitr_window':{
    'earliest':recovery.get('earliestRecoveryTime'),
    'latest':recovery.get('latestRecoveryTime'),
    'tested_point':recovery.get('latestRecoveryTime'),
  },
  'restored_instance':clone_name,
  'restored_state':clone.get('state'),
  'restored_database_version':clone.get('databaseVersion'),
  'verification_job':job_name,
  'verification_execution':execution.get('metadata',{}).get('name'),
  'api_image':image,
  'cleanup':'SCHEDULED_BY_EXIT_TRAP',
  'claims':{
    'pitr_clone_created':True,
    'restored_database_acceptance_gate_passed':True,
    'production_instance_not_overwritten':True,
  },
}
with open(out_path,'w',encoding='utf-8') as f:
    json.dump(out,f,sort_keys=True,indent=2); f.write('\n')
PY
printf 'PASS: Cloud SQL PITR clone was created and passed the production PostgreSQL/RLS acceptance gate.\n'
printf 'Evidence: %s\n' "$report"
