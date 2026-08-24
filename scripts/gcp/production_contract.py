"""Static, falsifiable contracts for the GCP production deployment graph."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Predicate:
    id: str
    passed: bool
    evidence: str


@dataclass(frozen=True)
class Sources:
    bootstrap: str
    foundation: str
    foundation_vars: str
    runtime_versions: str
    foundation_versions: str
    bootstrap_versions: str
    runtime_vars: str
    services: str
    worker: str
    lb: str
    monitoring: str
    edge_security: str
    installer: str
    production_workflow: str
    foundation_workflow: str
    drill_workflow: str
    assurance_workflow: str
    migration: str
    postgres_verify: str
    bootstrap_script: str
    gitignore: str
    all_tf: str
    versions: tuple[str, str, str]


def _read(root: Path, path: str) -> str:
    return (root / path).read_text(encoding="utf-8")


def load_sources(root: Path) -> Sources:
    bootstrap = _read(root, "infra/gcp/bootstrap/main.tf")
    foundation = _read(root, "infra/gcp/foundation/main.tf")
    runtime_versions = _read(root, "infra/gcp/runtime/versions.tf")
    foundation_versions = _read(root, "infra/gcp/foundation/versions.tf")
    bootstrap_versions = _read(root, "infra/gcp/bootstrap/versions.tf")
    all_tf = "\n".join(
        p.read_text(encoding="utf-8") for p in sorted((root / "infra/gcp").rglob("*.tf"))
    )
    return Sources(
        bootstrap=bootstrap,
        foundation=foundation,
        foundation_vars=_read(root, "infra/gcp/foundation/variables.tf"),
        runtime_versions=runtime_versions,
        foundation_versions=foundation_versions,
        bootstrap_versions=bootstrap_versions,
        runtime_vars=_read(root, "infra/gcp/runtime/variables.tf"),
        services=_read(root, "infra/gcp/runtime/services.tf"),
        worker=_read(root, "infra/gcp/runtime/worker.tf"),
        lb=_read(root, "infra/gcp/runtime/load_balancer.tf"),
        monitoring=_read(root, "infra/gcp/runtime/monitoring.tf"),
        edge_security=_read(root, "infra/gcp/foundation/edge_security.tf"),
        installer=_read(root, "scripts/gcp/install_terraform_verified.sh"),
        production_workflow=_read(root, ".github/workflows/gcp-production.yml"),
        foundation_workflow=_read(root, ".github/workflows/gcp-foundation.yml"),
        drill_workflow=_read(root, ".github/workflows/gcp-drill.yml"),
        assurance_workflow=_read(root, ".github/workflows/assurance.yml"),
        migration=_read(root, "infra/gcp/runtime/migration.tf"),
        postgres_verify=_read(root, "infra/gcp/runtime/postgres_verification.tf"),
        bootstrap_script=_read(root, "scripts/gcp/bootstrap_production.sh"),
        gitignore=_read(root, ".gitignore"),
        all_tf=all_tf,
        versions=(bootstrap_versions, foundation_versions, runtime_versions),
    )


def _group_01(s: Sources) -> list[Predicate]:
    p: list[Predicate] = []

    def add(i, ok, e):
        return p.append(Predicate(i, bool(ok), e))

    add(
        "TOOLCHAIN_TERRAFORM_PIN",
        all('required_version = "= 1.15.8"' in text for text in s.versions),
        "bootstrap/foundation/runtime pin Terraform 1.15.8",
    )
    add(
        "TOOLCHAIN_GOOGLE_PROVIDER_PIN",
        all('version = "= 7.43.0"' in text for text in s.versions),
        "bootstrap/foundation/runtime pin hashicorp/google 7.43.0",
    )
    add(
        "SUPPLY_TERRAFORM_SIGNATURE",
        "C874011F0AB405110D02105534365D9472D7468F" in s.installer
        and "gpg --batch --verify" in s.installer
        and ("sha256sum --check --strict" in s.installer),
        "installer authenticates signed checksums then verifies archive SHA-256",
    )
    add(
        "NO_TERRAFORM_SECRET_VALUES",
        "google_secret_manager_secret_version" not in s.all_tf and "secret_data" not in s.all_tf,
        "Terraform creates secret containers only; no secret payload resource is present",
    )
    add(
        "NO_SERVICE_ACCOUNT_KEYS",
        "google_service_account_key" not in s.all_tf and "credentials_json" not in s.all_tf,
        "no static Google service-account key resource or credentials_json path",
    )
    add(
        "WIF_PLANE_ISOLATION",
        all(
            token in s.bootstrap
            for token in (
                "foundation = {",
                "runtime = {",
                "drill = {",
                'pool_id       = "korpus-github-foundation"',
                'pool_id       = "korpus-github-runtime"',
                'pool_id       = "korpus-github-drill"',
                '"attribute.workflow_ref"        = "assertion.workflow_ref"',
                "assertion.repository == '${var.github_repository}'",
                "assertion.repository_id == '${var.github_repository_id}'",
                "assertion.repository_owner_id == '${var.github_owner_id}'",
                "assertion.ref == 'refs/heads/${var.github_deploy_branch}'",
                "assertion.workflow_ref == '${var.github_repository}/${each.value.workflow_path}@refs/heads/${var.github_deploy_branch}'",
            )
        )
        and "for_each = local.deployment_planes" in s.bootstrap,
        "foundation/runtime/drill each use a dedicated WIF pool/provider bound to immutable repository IDs, main ref, and exact workflow_ref",
    )
    add(
        "IDENTITY_SEPARATION",
        all(
            f'resource "google_service_account" "{name}"' in s.foundation
            for name in ("web", "api", "worker", "migrator")
        ),
        "web/api/worker/migrator use distinct service accounts",
    )
    add(
        "DEPLOYER_ACTAS_SCOPED",
        "roles/iam.serviceAccountUser" not in s.bootstrap
        and 'resource "google_service_account_iam_member" "github_deployer_act_as"' in s.foundation
        and ("for_each = local.runtime_service_account_resources" in s.foundation)
        and ('role               = "roles/iam.serviceAccountUser"' in s.foundation)
        and (
            'member             = "serviceAccount:${var.github_runtime_deployer_service_account}"'
            in s.foundation
        )
        and (
            "TF_VAR_github_runtime_deployer_service_account: ${{ vars.GCP_RUNTIME_DEPLOYER_SERVICE_ACCOUNT }}"
            in s.foundation_workflow
        ),
        "routine runtime deployer can actAs only the four dedicated KORPUS runtime service accounts; bootstrap grants no project-wide actAs",
    )
    add(
        "DELIVERY_PLANE_SEPARATION",
        "Apply foundation" not in s.production_workflow
        and "Seed non-Terraform runtime secret values" not in s.production_workflow
        and ("${{ vars.GCP_RUNTIME_WIF_PROVIDER }}" in s.production_workflow)
        and ("${{ vars.GCP_RUNTIME_DEPLOYER_SERVICE_ACCOUNT }}" in s.production_workflow)
        and ("Apply reviewed foundation plan" in s.foundation_workflow)
        and ("seed_runtime_secrets.sh" in s.foundation_workflow)
        and ("${{ vars.GCP_FOUNDATION_WIF_PROVIDER }}" in s.foundation_workflow)
        and ("${{ vars.GCP_FOUNDATION_DEPLOYER_SERVICE_ACCOUNT }}" in s.foundation_workflow),
        "routine production delivery cannot apply foundation or seed secret material; those mutations live in an isolated manual foundation workflow",
    )
    return p


def _group_02(s: Sources) -> list[Predicate]:
    p: list[Predicate] = []

    def add(i, ok, e):
        return p.append(Predicate(i, bool(ok), e))

    add(
        "DRILL_PLANE_ISOLATION",
        "${{ vars.GCP_DRILL_WIF_PROVIDER }}" in s.drill_workflow
        and "${{ vars.GCP_DRILL_DEPLOYER_SERVICE_ACCOUNT }}" in s.drill_workflow
        and ("${{ vars.GCP_RUNTIME_DEPLOYER_SERVICE_ACCOUNT }}" not in s.drill_workflow)
        and ('resource "google_project_iam_member" "drill_deployer"' in s.foundation)
        and all(
            role in s.foundation
            for role in ('"roles/cloudsql.admin"', '"roles/run.developer"', '"roles/run.invoker"')
        )
        and (
            'resource "google_artifact_registry_repository_iam_member" "drill_reader"'
            in s.foundation
        )
        and (
            'resource "google_service_account_iam_member" "drill_migrator_act_as"' in s.foundation
        ),
        "destructive-isolated PITR drill uses a dedicated WIF identity with Cloud SQL + temporary job permissions and actAs only the migrator",
    )
    add(
        "RUNTIME_CONTROL_PLANE_LEAST_PRIVILEGE",
        all(
            role in s.foundation
            for role in (
                '"roles/compute.loadBalancerAdmin"',
                '"roles/containeranalysis.occurrences.viewer"',
                '"roles/monitoring.editor"',
                '"roles/run.admin"',
            )
        )
        and 'resource "google_artifact_registry_repository_iam_member" "runtime_writer"'
        in s.foundation
        and (
            'resource "google_storage_bucket_iam_member" "runtime_governance_creator"'
            in s.foundation
        )
        and (
            'resource "google_storage_bucket_iam_member" "runtime_governance_viewer"'
            in s.foundation
        )
        and (
            "roles/secretmanager.admin"
            not in re.search(
                "locals \\{\\n  runtime_deployer_project_roles = toset\\(\\[(?P<body>.*?)\\n  \\]\\)\\n\\}",
                s.foundation,
                re.S,
            ).group("body")
        )
        and (
            "roles/cloudsql.admin"
            not in re.search(
                "locals \\{\\n  runtime_deployer_project_roles = toset\\(\\[(?P<body>.*?)\\n  \\]\\)\\n\\}",
                s.foundation,
                re.S,
            ).group("body")
        ),
        "routine runtime identity can deploy app/edge, write images/governance, and read scanner evidence but has no Secret Manager or Cloud SQL admin",
    )
    add(
        "WEB_NO_DATA_PLANE_IAM",
        "web      = google_service_account.web.email"
        not in re.search(
            "locals \\{\\n  database_clients = \\{(?P<body>.*?)\\n  \\}\\n\\}", s.foundation, re.S
        ).group("body")
        if re.search(
            "locals \\{\\n  database_clients = \\{(?P<body>.*?)\\n  \\}\\n\\}", s.foundation, re.S
        )
        else False,
        "web service account is excluded from database client set",
    )
    add(
        "WORKER_NO_UNUSED_METRICS_SECRET",
        '"worker-metrics"' not in s.foundation,
        "worker has no Secret Manager accessor binding for disabled metrics token",
    )
    add(
        "GCS_PUBLIC_ACCESS_PREVENTION",
        all(
            token in s.foundation
            for token in (
                "objects = {",
                "quarantine = {",
                "audit = {",
                "governance = {",
                "for_each = local.buckets",
                'public_access_prevention    = "enforced"',
            )
        ),
        "the four-key bucket map is instantiated through one PAP-enforced GCS resource",
    )
    add(
        "GCS_UNIFORM_ACCESS",
        all(
            token in s.foundation
            for token in (
                "objects = {",
                "quarantine = {",
                "audit = {",
                "governance = {",
                "for_each = local.buckets",
                "uniform_bucket_level_access = true",
            )
        ),
        "the four-key bucket map is instantiated through one uniform-access GCS resource",
    )
    custom_roles = "\n".join(
        re.findall('resource "google_project_iam_custom_role".*?\\n\\}', s.foundation, re.S)
    )
    add(
        "GCS_RUNTIME_NO_MUTATE_DELETE",
        "storage.objects.delete" not in custom_roles
        and "storage.objects.update" not in custom_roles,
        "runtime custom storage roles grant no update/delete permissions",
    )
    add(
        "WORKER_POOL_GA",
        'resource "google_cloud_run_v2_worker_pool" "ingestion"' in s.worker
        and 'launch_stage = "BETA"' not in s.worker
        and ('resource "google_cloud_run_v2_service" "ingestion"' not in s.worker),
        "ingestion uses the GA Cloud Run Worker Pool primitive rather than an HTTP service or beta launch-stage override",
    )
    return p


def _group_03(s: Sources) -> list[Predicate]:
    p: list[Predicate] = []

    def add(i, ok, e):
        return p.append(Predicate(i, bool(ok), e))

    add(
        "IMMUTABLE_RUNTIME_IMAGES",
        all(
            (m := re.search(f'variable "{name}" \\{{(?P<body>.*?)\\n\\}}', s.runtime_vars, re.S))
            is not None
            and 'regex("@sha256:[0-9a-f]{64}$", var.' + name + ")" in m.group("body")
            for name in ("api_image", "web_image", "clamav_image")
        ),
        "API, web, and ClamAV image variables require sha256 digest references",
    )
    add(
        "API_BACKGROUND_CPU",
        re.search(
            'resource "google_cloud_run_v2_service" "api".*?cpu_idle\\s*=\\s*false',
            s.services,
            re.S,
        )
        is not None,
        "API revision receives CPU outside request handling for reconciler task",
    )
    add(
        "WORKER_POOL_MANUAL_CAPACITY",
        'scaling_mode         = "MANUAL"' in s.worker
        and "manual_instance_count = var.worker_instances" in s.worker
        and (
            re.search(
                'variable "worker_instances" .*?condition\\s*=\\s*var\\.worker_instances >= 1',
                s.runtime_vars,
                re.S,
            )
            is not None
        ),
        "worker pool uses explicit non-zero manual capacity; it cannot silently scale to zero",
    )
    add(
        "SERVICE_SCALING_SSOT",
        s.services.count("scaling {") == 2 and s.worker.count("scaling {") == 1,
        "web/api each have one service scaling block and worker pool has one explicit manual-capacity block",
    )
    add(
        "EDGE_ONLY_INGRESS",
        s.services.count('ingress             = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"') == 2,
        "web and API accept network ingress only from internal/load-balancer paths",
    )
    add(
        "WORKER_POOL_DIRECT_NON_HTTP",
        'command    = ["python", "-m", "korpus.cli"]' in s.worker
        and 'args       = ["worker-loop", "--idle-seconds", "1"]' in s.worker
        and ("uvicorn" not in s.worker)
        and ("worker_service:app" not in s.worker)
        and ("ports {" not in s.worker),
        "worker pool executes the queue consumer directly and exposes no synthetic HTTP worker endpoint",
    )
    add(
        "WORKER_POOL_SIDECAR_ORDER",
        'depends_on = ["clamav"]' in s.worker
        and re.search(
            'containers \\{\\n      name  = "clamav".*?startup_probe \\{.*?tcp_socket \\{\\n          port = 3310',
            s.worker,
            re.S,
        )
        is not None,
        "ingestion starts only after the ClamAV sidecar passes an explicit startup probe",
    )
    add(
        "WORKER_POOL_DATA_MOUNTS",
        "cloud_sql_instance {" in s.worker
        and "gcs {" in s.worker
        and (s.worker.count("secret {") >= 2)
        and ('mount_path = "/cloudsql"' in s.worker)
        and ('mount_path = "/etc/korpus/governance"' in s.worker),
        "worker pool retains Cloud SQL connector, read-only governance GCS, and secret-volume contracts",
    )
    add(
        "LB_API_FAIL_CLOSED_ROUTING",
        all(
            token in s.lb
            for token in (
                'full_path_match = "/api"',
                'prefix_match = "/api/"',
                'path_prefix_rewrite = "/"',
                'path                = "/api"',
                'path                = "/api/v1/auth/me"',
                "service             = google_compute_backend_service.api.id",
            )
        ),
        "load balancer routes exact /api and /api/* to API and has URL-map tests",
    )
    add(
        "MONITORING_HOST_SCOPED",
        'resource.label.host=\\"${var.domain}\\"' in s.monitoring,
        "uptime alert condition is scoped to canonical production host",
    )
    add(
        "MONITORING_DELIVERY_REQUIRED",
        s.monitoring.count('resource "google_monitoring_alert_policy"') > 0
        and s.monitoring.count("notification_channels = var.notification_channel_ids")
        == s.monitoring.count('resource "google_monitoring_alert_policy"')
        and "length(var.notification_channel_ids) >= 1" in s.runtime_vars,
        "every production alert policy is bound to explicit notification channels and production requires at least one channel",
    )
    add(
        "ARTIFACT_ANALYSIS_ENABLED",
        '"containeranalysis.googleapis.com"' in s.foundation
        and '"containerscanning.googleapis.com"' in s.foundation,
        "foundation enables Artifact Analysis metadata and automatic container scanning APIs",
    )
    add(
        "ARTIFACT_ANALYSIS_LEAST_PRIVILEGE",
        '"roles/containeranalysis.occurrences.viewer"' in s.foundation
        and '"roles/containeranalysis.admin"' not in s.bootstrap
        and ('"roles/containeranalysis.admin"' not in s.foundation),
        "runtime deployment identity can read vulnerability occurrences without Container Analysis admin",
    )
    return p


def _group_04(s: Sources) -> list[Predicate]:
    p: list[Predicate] = []

    def add(i, ok, e):
        return p.append(Predicate(i, bool(ok), e))

    add(
        "PRODUCTION_WORKFLOW_KEYLESS",
        "google-github-actions/auth@7c6bc770dae815cd3e89ee6cdf493a5fab2cc093"
        in s.production_workflow
        and "workload_identity_provider:" in s.production_workflow
        and ("service_account:" in s.production_workflow)
        and ("credentials_json:" not in s.production_workflow),
        "production workflow uses SHA-pinned Google auth with WIF and no key JSON input",
    )
    add(
        "PRODUCTION_WORKFLOW_ACTION_PINS",
        all(
            token in s.production_workflow
            for token in (
                "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
                "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
                "google-github-actions/setup-gcloud@aa5489c8933f4cc7a4f7d45035b3b1440c9c10db",
                "actions/attest@a1948c3f048ba23858d222213b7c278aabede763",
                "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
            )
        ),
        "all third-party actions in production workflow are full-SHA pinned",
    )
    ordered = [
        "Publish immutable governance bundle",
        "Build, mirror, and push immutable candidates",
        "Gate Artifact Analysis vulnerabilities",
        "Materialize migration job before application services",
        "Verify live PostgreSQL and FORCE RLS boundary",
        "Capture serving revisions for rollback",
        "Plan runtime from immutable evidence",
        "Apply reviewed runtime plan",
        "Execute exact private candidate probe",
        "Promote candidate to bounded canary traffic",
        "Admit candidate by revision metrics",
        "Promote verified candidate to 100 percent",
        "Verify public production edge",
    ]
    positions = [s.production_workflow.find(name) for name in ordered]
    add(
        "PRODUCTION_WORKFLOW_ORDER",
        all(pos >= 0 for pos in positions) and positions == sorted(positions),
        "deploy order is governance -> build -> scan -> migrate -> live PostgreSQL/RLS gate -> predecessor snapshot -> fresh plan -> apply at tagged candidate -> exact probe -> bounded canary -> revision metrics -> full promotion -> live smoke",
    )
    add(
        "PRODUCTION_WORKFLOW_DISABLED_BY_DEFAULT",
        "vars.GCP_PRODUCTION_ENABLED == 'true'" in s.production_workflow
        and "environment: production" in s.production_workflow,
        "cloud mutation is gated by an explicit repository variable and named GitHub environment; live environment protection is verified by bootstrap evidence, not asserted here",
    )
    add(
        "PRODUCTION_WORKFLOW_VERIFIED_TERRAFORM",
        'scripts/gcp/install_terraform_verified.sh "${TERRAFORM_VERSION}"' in s.production_workflow
        and "terraform fmt -check -recursive infra/gcp" in s.production_workflow
        and ('terraform -chdir="infra/gcp/${stack}" validate' in s.production_workflow),
        "workflow installs signature-verified Terraform and validates every stack before deploy",
    )
    add(
        "BOOTSTRAP_REMOTE_STATE_TRUST_ROOT",
        'backend "gcs" {}' in s.bootstrap_versions
        and "gcloud storage buckets create" in s.bootstrap_script
        and ("google_storage_bucket.terraform_state" in s.bootstrap_script)
        and ('terraform -chdir="$BOOTSTRAP_DIR" import' in s.bootstrap_script)
        and ("**/.terraform/" in s.gitignore)
        and ("*.tfstate" in s.gitignore),
        "state bucket is securely pre-created, immediately imported into GCS-backed Terraform state, and local Terraform state/cache artifacts are ignored",
    )
    add(
        "BOOTSTRAP_GITHUB_BRANCH_GATE",
        all(
            token in s.bootstrap_script
            for token in (
                "github_repository_id",
                "github_owner_id",
                "custom_branch_policies",
                "deployment-branch-policies",
                'set_repo_var GCP_FOUNDATION_ENABLED "false"',
                'set_repo_var GCP_PRODUCTION_ENABLED "false"',
                "production-foundation",
                "required_reviewer_claim",
            )
        ),
        "bootstrap binds immutable GitHub IDs, configures selected-branch production environment, and leaves production disabled without inventing an independent reviewer",
    )
    add(
        "MIGRATION_SECRET_RESOLUTION_ENTRYPOINT",
        'command = ["/usr/local/bin/korpus-entrypoint"]' in s.migration
        and "KORPUS_DATABASE_URL_TEMPLATE" in s.migration
        and ("KORPUS_DATABASE_PASSWORD_FILE" in s.migration),
        "migration job executes the image secret-resolving entrypoint before Alembic/role provisioning",
    )
    add(
        "LIVE_POSTGRES_RLS_GATE",
        'resource "google_cloud_run_v2_job" "postgres_verify"' in s.postgres_verify
        and 'command = ["/usr/local/bin/korpus-entrypoint"]' in s.postgres_verify
        and ("scripts/gcp/verify_live_postgres.py" in s.postgres_verify)
        and ("-target=google_cloud_run_v2_job.postgres_verify" in s.production_workflow)
        and ("gcloud run jobs execute korpus-postgres-verify" in s.production_workflow),
        "a non-destructive Cloud SQL job verifies schema, app-role least privilege, exact grants, FORCE RLS and denial paths after migration and before full rollout",
    )
    return p


def evaluate(root: Path) -> list[Predicate]:
    from scripts.gcp.production_contract_external import evaluate as external_predicates

    s = load_sources(root)
    return [
        *_group_01(s),
        *_group_02(s),
        *_group_03(s),
        *_group_04(s),
        *(Predicate(i, ok, evidence) for i, ok, evidence in external_predicates(s)),
    ]
