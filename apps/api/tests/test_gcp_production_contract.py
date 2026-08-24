from __future__ import annotations

import shutil
from pathlib import Path

from scripts.verify_gcp_production import evaluate

ROOT = Path(__file__).resolve().parents[3]


def _status(root: Path) -> dict[str, bool]:
    return {item.id: item.passed for item in evaluate(root)}


def _mutated_repo(tmp_path: Path, relative: str, old: str, new: str) -> Path:
    # Copy only the verifier's production contract surface, not the entire repository.
    for source in [
        "infra/gcp/bootstrap/main.tf",
        "infra/gcp/bootstrap/versions.tf",
        "infra/gcp/foundation/main.tf",
        "infra/gcp/foundation/network.tf",
        "infra/gcp/foundation/outputs.tf",
        "infra/gcp/foundation/variables.tf",
        "infra/gcp/foundation/versions.tf",
        "infra/gcp/foundation/edge_security.tf",
        "infra/gcp/runtime/versions.tf",
        "infra/gcp/runtime/variables.tf",
        "infra/gcp/runtime/locals.tf",
        "infra/gcp/runtime/services.tf",
        "infra/gcp/runtime/worker.tf",
        "infra/gcp/runtime/canary.tf",
        "infra/gcp/runtime/load_balancer.tf",
        "infra/gcp/runtime/monitoring.tf",
        "infra/gcp/runtime/migration.tf",
        "infra/gcp/runtime/postgres_verification.tf",
        "scripts/gcp/install_terraform_verified.sh",
        "scripts/gcp/bootstrap_production.sh",
        ".github/workflows/gcp-production.yml",
        ".github/workflows/gcp-foundation.yml",
        ".github/workflows/gcp-drill.yml",
        ".github/workflows/assurance.yml",
        ".gitignore",
    ]:
        dst = tmp_path / source
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / source, dst)
    target = tmp_path / relative
    text = target.read_text(encoding="utf-8")
    assert old in text
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
    return tmp_path


def test_current_gcp_production_contract_passes() -> None:
    status = _status(ROOT)
    assert status and all(status.values()), [name for name, ok in status.items() if not ok]


def test_connector_enforcement_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "infra/gcp/foundation/main.tf",
        'connector_enforcement       = "REQUIRED"',
        'connector_enforcement       = "NOT_REQUIRED"',
    )
    assert _status(root)["CLOUDSQL_CONNECTOR_ONLY"] is False


def test_worker_pool_autoscaling_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "infra/gcp/runtime/worker.tf",
        'scaling_mode         = "MANUAL"',
        'scaling_mode         = "AUTOMATIC"',
    )
    assert _status(root)["WORKER_POOL_MANUAL_CAPACITY"] is False


def test_worker_pool_http_shim_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "infra/gcp/runtime/worker.tf",
        'command    = ["python", "-m", "korpus.cli"]',
        'command    = ["python", "-m", "uvicorn"]',
    )
    assert _status(root)["WORKER_POOL_DIRECT_NON_HTTP"] is False


def test_worker_sidecar_dependency_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path, "infra/gcp/runtime/worker.tf", 'depends_on = ["clamav"]', "depends_on = []"
    )
    assert _status(root)["WORKER_POOL_SIDECAR_ORDER"] is False


def test_unsigned_image_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "infra/gcp/runtime/variables.tf",
        "@sha256:[0-9a-f]{64}$",
        ":latest$",
    )
    assert _status(root)["IMMUTABLE_RUNTIME_IMAGES"] is False


def test_alert_delivery_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "infra/gcp/runtime/monitoring.tf",
        "notification_channels = var.notification_channel_ids",
        "# notification disabled",
    )
    assert _status(root)["MONITORING_DELIVERY_REQUIRED"] is False


def test_production_sequence_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        ".github/workflows/gcp-production.yml",
        "      - name: Gate Artifact Analysis vulnerabilities",
        "      - name: Container security checkpoint",
    )
    # Renaming removes the exact ordered acceptance checkpoint.
    assert _status(root)["PRODUCTION_WORKFLOW_ORDER"] is False


def test_static_credentials_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        ".github/workflows/gcp-production.yml",
        "          project_id: ${{ vars.GCP_PROJECT_ID }}",
        "          credentials_json: ${{ secrets.GCP_KEY_JSON }}",
    )
    assert _status(root)["PRODUCTION_WORKFLOW_KEYLESS"] is False


def test_scanner_api_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "infra/gcp/foundation/main.tf",
        '    "containerscanning.googleapis.com",',
        "    # scanning disabled",
    )
    assert _status(root)["ARTIFACT_ANALYSIS_ENABLED"] is False


def test_migration_entrypoint_bypass_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "infra/gcp/runtime/migration.tf",
        'command = ["/usr/local/bin/korpus-entrypoint"]',
        'command = ["/bin/sh"]',
    )
    assert _status(root)["MIGRATION_SECRET_RESOLUTION_ENTRYPOINT"] is False


def test_live_postgres_gate_removal_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        ".github/workflows/gcp-production.yml",
        "      - name: Verify live PostgreSQL and FORCE RLS boundary",
        "      - name: Database checkpoint removed",
    )
    assert _status(root)["PRODUCTION_WORKFLOW_ORDER"] is False


def test_bootstrap_cannot_enable_production_by_default(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "scripts/gcp/bootstrap_production.sh",
        'set_repo_var GCP_PRODUCTION_ENABLED "false"',
        'set_repo_var GCP_PRODUCTION_ENABLED "true"',
    )
    assert _status(root)["BOOTSTRAP_GITHUB_BRANCH_GATE"] is False


def test_project_wide_act_as_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "infra/gcp/bootstrap/main.tf",
        '"roles/storage.admin",',
        '"roles/storage.admin",\n    "roles/iam.serviceAccountUser",',
    )
    assert _status(root)["DEPLOYER_ACTAS_SCOPED"] is False


def test_runtime_secret_admin_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "infra/gcp/foundation/main.tf",
        '"roles/run.admin",',
        '"roles/run.admin",\n    "roles/secretmanager.admin",',
    )
    assert _status(root)["RUNTIME_CONTROL_PLANE_LEAST_PRIVILEGE"] is False


def test_runtime_workflow_foundation_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        ".github/workflows/gcp-production.yml",
        "      - name: Initialize foundation state read-only",
        "      - name: Apply foundation",
    )
    assert _status(root)["DELIVERY_PLANE_SEPARATION"] is False


def test_cloud_armor_detachment_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "infra/gcp/runtime/load_balancer.tf",
        "  security_policy       = local.foundation.edge_security_policy_self_link",
        "  # security policy detached",
    )
    assert _status(root)["EDGE_CLOUD_ARMOR_ATTACHED"] is False


def test_cloud_armor_waf_preview_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "infra/gcp/foundation/edge_security.tf",
        "    preview     = false",
        "    preview     = true",
    )
    assert _status(root)["EDGE_WAF_ENFORCED"] is False


def test_edge_policy_mutation_privilege_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "infra/gcp/foundation/main.tf",
        '    "compute.securityPolicies.use",',
        '    "compute.securityPolicies.use",\n    "compute.securityPolicies.update",',
    )
    assert _status(root)["RUNTIME_EDGE_POLICY_LEAST_PRIVILEGE"] is False


def test_terraform_pin_downgrade_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "infra/gcp/runtime/versions.tf",
        'required_version = "= 1.15.8"',
        'required_version = "= 1.15.5"',
    )
    assert _status(root)["TOOLCHAIN_TERRAFORM_PIN"] is False


def test_deep_readiness_monitor_removal_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "infra/gcp/runtime/monitoring.tf",
        '    path           = "/api/ready"',
        '    path           = "/healthz"',
    )
    assert _status(root)["API_DEEP_READINESS_MONITOR"] is False


def test_daily_assurance_schedule_removal_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        ".github/workflows/assurance.yml",
        '    - cron: "17 3 * * *"',
        "    # schedule removed",
    )
    assert _status(root)["AUTONOMOUS_ASSURANCE_SCHEDULE"] is False


def test_monthly_pitr_schedule_removal_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        ".github/workflows/gcp-drill.yml",
        '    - cron: "37 3 1 * *"',
        "    # schedule removed",
    )
    assert _status(root)["AUTONOMOUS_PITR_DRILL_SCHEDULE"] is False


def test_uptime_absence_detector_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "infra/gcp/runtime/monitoring.tf",
        "    condition_absent {",
        "    condition_threshold {",
    )
    assert _status(root)["UPTIME_TELEMETRY_FAIL_CLOSED"] is False


def test_tls_expiry_alert_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "infra/gcp/runtime/monitoring.tf",
        'metric.type=\\"monitoring.googleapis.com/uptime_check/time_until_ssl_cert_expires\\"',
        'metric.type=\\"monitoring.googleapis.com/uptime_check/check_passed\\"',
    )
    assert _status(root)["TLS_EXPIRY_ALERT"] is False


def test_provenance_admission_signer_policy_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        ".github/workflows/gcp-production.yml",
        '--signer-workflow "${signer_workflow}"',
        '--signer-repo "${GITHUB_REPOSITORY}"',
    )
    assert _status(root)["PROVENANCE_ADMISSION_ENFORCED"] is False


def test_automatic_rollback_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        ".github/workflows/gcp-production.yml",
        "      - name: Roll back Cloud Run traffic on failed promotion",
        "      - name: Rollback disabled",
    )
    assert _status(root)["AUTOMATIC_TRAFFIC_ROLLBACK"] is False


def test_migration_compatibility_admission_removal_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        ".github/workflows/gcp-production.yml",
        "      - name: Validate migration expand-contract compatibility",
        "      - name: Migration compatibility bypassed",
    )
    assert _status(root)["EXPAND_CONTRACT_MIGRATION_ADMISSION"] is False


def test_unbounded_cloudsql_autogrowth_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "infra/gcp/foundation/main.tf",
        "    disk_autoresize_limit       = var.database_disk_autoresize_limit_gb",
        "    disk_autoresize_limit       = 0",
    )
    assert _status(root)["CLOUDSQL_BOUNDED_AUTOGROWTH"] is False


def test_cloudsql_duplicate_lifecycle_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "infra/gcp/foundation/main.tf",
        "  depends_on = [google_project_service.required]",
        "  lifecycle {\n    ignore_changes = [settings[0].disk_size]\n  }\n\n  depends_on = [google_project_service.required]",
    )
    assert _status(root)["CLOUDSQL_BOUNDED_AUTOGROWTH"] is False


def test_unbounded_web_autoscaling_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "infra/gcp/runtime/variables.tf",
        "var.web_max_instances >= var.web_min_instances && var.web_max_instances <= 100",
        "var.web_max_instances >= var.web_min_instances",
    )
    assert _status(root)["FINITE_RUNTIME_CAPACITY"] is False


def test_terraform_structural_admission_removal_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        ".github/workflows/gcp-production.yml",
        "python scripts/gcp/validate_terraform_structure.py --output reports/TERRAFORM_STRUCTURE.json",
        "echo structural-gate-bypassed",
    )
    assert _status(root)["TERRAFORM_STRUCTURAL_ADMISSION"] is False


def test_tls_policy_downgrade_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "infra/gcp/runtime/load_balancer.tf",
        'min_tls_version = "TLS_1_2"',
        'min_tls_version = "TLS_1_0"',
    )
    assert _status(root)["EDGE_TLS_POLICY_ENFORCED"] is False


def test_cloudsql_public_ipv4_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "infra/gcp/foundation/main.tf",
        "      ipv4_enabled    = false",
        "      ipv4_enabled    = true",
    )
    assert _status(root)["CLOUDSQL_PRIVATE_ONLY"] is False


def test_private_services_access_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "infra/gcp/foundation/network.tf",
        '  service                 = "servicenetworking.googleapis.com"',
        '  service                 = "example.invalid"',
    )
    assert _status(root)["PRIVATE_SERVICES_ACCESS"] is False


def test_api_direct_vpc_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "infra/gcp/runtime/services.tf",
        '      egress = "PRIVATE_RANGES_ONLY"',
        '      egress = "ALL_TRAFFIC"',
    )
    assert _status(root)["RUNTIME_DIRECT_VPC_DB_PLANE"] is False


def test_worker_direct_vpc_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "infra/gcp/runtime/worker.tf",
        '      egress = "PRIVATE_RANGES_ONLY"',
        '      egress = "ALL_TRAFFIC"',
    )
    assert _status(root)["RUNTIME_DIRECT_VPC_DB_PLANE"] is False


def test_migration_direct_vpc_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "infra/gcp/runtime/migration.tf",
        '        egress = "PRIVATE_RANGES_ONLY"',
        '        egress = "ALL_TRAFFIC"',
    )
    assert _status(root)["RUNTIME_DIRECT_VPC_DB_PLANE"] is False


def test_postgres_verify_direct_vpc_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "infra/gcp/runtime/postgres_verification.tf",
        '        egress = "PRIVATE_RANGES_ONLY"',
        '        egress = "ALL_TRAFFIC"',
    )
    assert _status(root)["RUNTIME_DIRECT_VPC_DB_PLANE"] is False


def test_candidate_zero_traffic_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "infra/gcp/runtime/services.tf",
        'tag     = "candidate"',
        'tag     = "unchecked"',
    )
    assert _status(root)["ZERO_TRAFFIC_CANDIDATE"] is False


def test_candidate_probe_vpc_mutation_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        "infra/gcp/runtime/canary.tf",
        'egress = "ALL_TRAFFIC"',
        'egress = "PRIVATE_RANGES_ONLY"',
    )
    assert _status(root)["PRIVATE_EXACT_CANDIDATE_PROBE"] is False


def test_canary_metric_admission_removal_is_killed(tmp_path: Path) -> None:
    root = _mutated_repo(
        tmp_path,
        ".github/workflows/gcp-production.yml",
        "      - name: Admit candidate by revision metrics",
        "      - name: Skip candidate metric admission",
    )
    assert _status(root)["STAGED_TRAFFIC_PROMOTION"] is False
