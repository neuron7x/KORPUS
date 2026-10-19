"""Canonical GitHub authority and inert legacy-GitLab predicates."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import yaml
from korpus.gitlab_tombstone_contract import (
    gitlab_delivery_is_inert,
    gitlab_pipeline_globally_disabled,
    gitlab_tombstone,
)

if TYPE_CHECKING:
    from scripts.gcp.production_contract import Sources


def _object(source: str, *, yaml_source: bool) -> dict[str, Any]:
    try:
        value = yaml.safe_load(source) if yaml_source else json.loads(source)
    except (yaml.YAMLError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _github_bound(s: Sources) -> bool:
    return (
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


def evaluate(s: Sources) -> list[tuple[str, bool, str]]:
    config = _object(s.gitlab_ci, yaml_source=True)
    policy = _object(s.gitlab_policy, yaml_source=False)
    release_retired = gitlab_tombstone(config, "production:release")
    deploy_retired = gitlab_tombstone(config, "gcp:deploy-production")
    return [
        (
            "GITHUB_PRODUCTION_AUTHORITY_BOUND",
            _github_bound(s),
            "GitHub main, immutable repository identities, exact production workflow, and runtime WIF are jointly bound",
        ),
        (
            "GITLAB_PIPELINE_GLOBALLY_DISABLED",
            gitlab_pipeline_globally_disabled(config),
            "GitLab creates no pipeline and therefore executes no repository-controlled code",
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
            release_retired and deploy_retired and gitlab_delivery_is_inert(config, policy),
            "GitLab is the exact globally disabled legacy pipeline and has no execution path",
        ),
    ]
