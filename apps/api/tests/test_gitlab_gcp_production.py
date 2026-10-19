from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
_MUTATING = re.compile(
    r"(?:\b(?:git|docker|podman|oras|crane)\s+push\b|\b(?:gh|glab)\s+release\b|"
    r"\b(?:npm|pnpm|yarn)\s+publish\b|\btwine\s+upload\b|"
    r"\bgcloud\b[^\n]*\bdeploy\b|\bterraform\s+(?:apply|destroy)\b|"
    r"\bkubectl\s+(?:apply|delete)\b|\bhelm\s+(?:install|upgrade|push)\b|"
    r"\bcurl\b[^\n]*(?:-X|--request)\s*(?:POST|PUT|PATCH|DELETE)\b|"
    r"package_production_release\.sh|deploy_[A-Za-z0-9_.-]+\.sh)"
)


def _mutating_commands(ci: dict[object, object]) -> list[str]:
    offenders: list[str] = []
    for name, job in ci.items():
        if not isinstance(job, dict):
            continue
        for field in ("before_script", "script", "after_script"):
            commands = job.get(field) or []
            if not isinstance(commands, list):
                continue
            for command in commands:
                line = str(command)
                if line.lstrip().startswith("bash -n "):
                    continue
                if "/kaniko/executor" in line and "--no-push" in line:
                    continue
                if "/kaniko/executor" in line or _MUTATING.search(line):
                    offenders.append(f"{name}.{field}: {line}")
    return offenders


def test_gitlab_pipeline_and_release_deploy_jobs_are_inert() -> None:
    ci = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    assert ci["workflow"] == {"rules": [{"when": "never"}]}
    for name in ("production:release", "gcp:deploy-production"):
        job = ci[name]
        assert set(job) == {"stage", "rules", "script"}
        assert job["rules"] == [{"when": "never"}]
        assert job["script"][-1] == "exit 1"
        assert not ({"environment", "id_tokens", "needs", "artifacts"} & set(job))


def test_gitlab_pipeline_has_no_executable_publish_or_deploy_command() -> None:
    ci = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    assert _mutating_commands(ci) == []


def test_gitlab_read_only_scanner_rejects_mutating_commands() -> None:
    poisoned = {
        "publish": {
            "script": [
                "git push origin main",
                "curl -X POST https://gitlab.example/releases",
                "/kaniko/executor --destination registry.example/korpus:latest",
            ]
        }
    }
    assert len(_mutating_commands(poisoned)) == 3


def test_legacy_gitlab_wif_provider_remains_fail_closed_for_static_provenance() -> None:
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


def test_gitlab_deployment_script_keeps_safe_order_as_nonexecuting_provenance() -> None:
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
