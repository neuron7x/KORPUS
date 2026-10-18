"""Canonical GitHub authority and inert legacy-GitLab predicates."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from scripts.gcp.production_contract import Sources

CONTROL_KEYS = {"workflow", "default", "stages", "variables"}
FORBIDDEN_KEYS = {"include", "trigger", "id_tokens", "identity", "environment", "resource_group"}
PIPELINE_SHA256 = "dab0145c5b86d0dc81aed8ce13840f5459be822bcd35c00a5d924a732b02b79b"
POLICY_SHA256 = "57bdecb6343ceaa92c68f10db22b939fb849309590f617325a3162caf7c31802"
TOMBSTONES = {
    "production:release": (
        "release",
        'echo "GitLab release authority is retired; use canonical GitHub release workflow" >&2',
    ),
    "gcp:deploy-production": (
        "deploy",
        'echo "GitLab deploy authority is retired; use canonical GitHub workflows" >&2',
    ),
}


def _object(source: str, *, yaml_source: bool) -> dict[str, Any]:
    try:
        value = yaml.safe_load(source) if yaml_source else json.loads(source)
    except (yaml.YAMLError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _contains_forbidden_key(value: object) -> bool:
    if isinstance(value, Mapping):
        return bool(FORBIDDEN_KEYS & set(value)) or any(
            _contains_forbidden_key(item) for item in value.values()
        )
    return isinstance(value, list) and any(_contains_forbidden_key(item) for item in value)


def _tombstone(config: Mapping[str, Any], name: str) -> bool:
    stage, marker = TOMBSTONES[name]
    job = config.get(name)
    return bool(
        isinstance(job, Mapping)
        and set(job) == {"stage", "rules", "script"}
        and job.get("stage") == stage
        and job.get("rules") == [{"when": "never"}]
        and job.get("script") == [marker, "exit 1"]
    )


def _pipeline_inert(config: Mapping[str, Any], policy: Mapping[str, Any]) -> bool:
    jobs = policy.get("allowed_job_sha256")
    if _digest(policy) != POLICY_SHA256 or not isinstance(jobs, Mapping):
        return False
    if (
        _digest(config) != PIPELINE_SHA256
        or set(config) != CONTROL_KEYS | set(jobs)
        or _contains_forbidden_key(config)
    ):
        return False
    return all(_digest(config.get(name)) == digest for name, digest in jobs.items()) and all(
        _tombstone(config, name) for name in TOMBSTONES
    )


def evaluate(s: Sources) -> list[tuple[str, bool, str]]:
    config = _object(s.gitlab_ci, yaml_source=True)
    policy = _object(s.gitlab_policy, yaml_source=False)
    release_retired = _tombstone(config, "production:release")
    deploy_retired = _tombstone(config, "gcp:deploy-production")
    github_bound = (
        'issuer_uri = "https://token.actions.githubusercontent.com"' in s.bootstrap
        and "assertion.repository_id == '${var.github_repository_id}'" in s.bootstrap
        and "assertion.repository_owner_id == '${var.github_owner_id}'" in s.bootstrap
        and "assertion.ref == 'refs/heads/${var.github_deploy_branch}'" in s.bootstrap
        and (
            "assertion.workflow_ref == '${var.github_repository}/${each.value.workflow_path}@refs/heads/${var.github_deploy_branch}'"
            in s.bootstrap
        )
        and 'workflow_path = ".github/workflows/gcp-production.yml"' in s.bootstrap
        and "${{ vars.GCP_RUNTIME_WIF_PROVIDER }}" in s.production_workflow
        and "${{ vars.GCP_RUNTIME_DEPLOYER_SERVICE_ACCOUNT }}" in s.production_workflow
        and "environment: production" in s.production_workflow
    )
    return [
        (
            "GITHUB_PRODUCTION_AUTHORITY_BOUND",
            github_bound,
            "GitHub main, immutable repository identities, exact production workflow, and runtime WIF are jointly bound",
        ),
        (
            "GITLAB_RELEASE_AUTHORITY_RETIRED",
            release_retired,
            "GitLab release job is an exact never-scheduled fail-closed tombstone",
        ),
        (
            "GITLAB_DEPLOY_AUTHORITY_RETIRED",
            deploy_retired,
            "GitLab production deploy job is an exact never-scheduled fail-closed tombstone",
        ),
        (
            "GITLAB_WIF_AND_MUTATION_PATHS_ABSENT",
            release_retired and deploy_retired and _pipeline_inert(config, policy),
            "GitLab is exactly the admitted read-only validation pipeline and has no delegated execution path",
        ),
    ]
