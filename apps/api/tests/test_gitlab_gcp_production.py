from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def test_gitlab_production_job_is_keyless_serialized_and_fail_closed() -> None:
    ci = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    job = ci["gcp:deploy-production"]
    rule = job["rules"][0]
    assert job["interruptible"] is False
    assert job["resource_group"] == "gcp-production"
    assert job["environment"] == {
        "name": "production",
        "deployment_tier": "production",
        "url": "https://$KORPUS_DOMAIN",
    }
    assert job["id_tokens"]["GCP_ID_TOKEN"]["aud"] == "$GCP_WIF_AUDIENCE"
    assert rule["when"] == "manual"
    for predicate in ("main", "CI_COMMIT_REF_PROTECTED", "GCP_PRODUCTION_ENABLED"):
        assert predicate in rule["if"]
    needed = {item["job"] for item in job["needs"]}
    assert {"container:build", "container:scan", "gcp:production-contract"} <= needed
    script = "\n".join(job["script"])
    assert "authenticate_gitlab_wif.sh" in script
    assert "deploy_gitlab_production.sh" in script
    assert "credentials_json" not in str(job)


def test_gitlab_wif_provider_binds_immutable_project_and_protected_environment() -> None:
    bootstrap = (ROOT / "infra/gcp/bootstrap/main.tf").read_text(encoding="utf-8")
    for claim in (
        "assertion.project_id == '${var.gitlab_project_id}'",
        "assertion.namespace_id == '${var.gitlab_namespace_id}'",
        "assertion.ref_type == 'branch'",
        "assertion.ref == '${var.gitlab_deploy_branch}'",
        "assertion.ref_protected == 'true'",
        "assertion.environment == 'production'",
        "assertion.environment_protected == 'true'",
        "assertion.deployment_tier == 'production'",
    ):
        assert claim in bootstrap
    assert 'issuer_uri = "https://gitlab.com"' in bootstrap
    assert 'resource "google_service_account" "gitlab_deployer"' in bootstrap
    assert 'resource "google_iam_workload_identity_pool" "gitlab"' in bootstrap
    assert 'google_service_account.gitlab_deployer["runtime"]' in bootstrap


def test_gitlab_authentication_refuses_wrong_delivery_context() -> None:
    script = (ROOT / "scripts/gcp/authenticate_gitlab_wif.sh").read_text(encoding="utf-8")
    for predicate in (
        '[[ "$CI_PROJECT_ID" == "85043500" ]]',
        '[[ "$CI_COMMIT_BRANCH" == "main" ]]',
        '[[ "$CI_COMMIT_REF_PROTECTED" == "true" ]]',
        '[[ "$CI_ENVIRONMENT_NAME" == "production" ]]',
        '[[ "$CI_ENVIRONMENT_TIER" == "production" ]]',
    ):
        assert predicate in script
    assert "create-cred-config" in script
    assert "service-account-token-lifetime-seconds=900" in script
    assert "activate-service-account" not in script
    assert "--key-file" not in script


def test_gitlab_deployment_orders_migration_probe_canary_and_rollback() -> None:
    script = (ROOT / "scripts/gcp/deploy_gitlab_production.sh").read_text(encoding="utf-8")
    ordered = (
        "verify_container_vulnerabilities.py",
        "validate_migration_compatibility.py",
        "korpus-migrate",
        "korpus-postgres-verify",
        "terraform -chdir=infra/gcp/runtime plan",
        "korpus-candidate-probe",
        "canary_metrics.py",
        "--to-tags=candidate=100",
        "live_smoke.py",
    )
    positions = [script.index(token) for token in ordered]
    assert positions == sorted(positions)
    assert "trap rollback ERR" in script
    assert "rollback_traffic.py" in script
    assert "api-image.tar" in script and "web-image.tar" in script
