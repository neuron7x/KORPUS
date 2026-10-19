from __future__ import annotations

import re
from collections.abc import Mapping

CANONICAL_GITHUB_REPOSITORY = "neuron7x/KORPUS"
CANONICAL_GITHUB_REPOSITORY_ID = "1332311807"
CANONICAL_GITHUB_OWNER_ID = "206596321"
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
POSITIVE_INTEGER = re.compile(r"^[1-9][0-9]*$")


def expected_github_release_environment(release: str) -> dict[str, str]:
    ref = f"refs/tags/{release}"
    return {
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": CANONICAL_GITHUB_REPOSITORY,
        "GITHUB_REPOSITORY_ID": CANONICAL_GITHUB_REPOSITORY_ID,
        "GITHUB_REPOSITORY_OWNER_ID": CANONICAL_GITHUB_OWNER_ID,
        "GITHUB_REF_PROTECTED": "true",
        "GITHUB_REF_TYPE": "tag",
        "GITHUB_REF_NAME": release,
        "GITHUB_REF": ref,
        "GITHUB_WORKFLOW_REF": (
            f"{CANONICAL_GITHUB_REPOSITORY}/.github/workflows/release.yml@{ref}"
        ),
        "RUNNER_ENVIRONMENT": "github-hosted",
    }


def github_release_context_mismatches(environment: Mapping[str, str], release: str) -> list[str]:
    expected = expected_github_release_environment(release)
    mismatches = [name for name, value in expected.items() if environment.get(name) != value]
    if environment.get("GITLAB_CI") == "true":
        mismatches.append("GITLAB_CI")
    if not GIT_SHA.fullmatch(environment.get("GITHUB_SHA", "")):
        mismatches.append("GITHUB_SHA")
    return sorted(mismatches)
