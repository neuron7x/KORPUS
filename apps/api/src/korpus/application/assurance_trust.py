from __future__ import annotations

import json
import os
import re
from pathlib import Path

from korpus.release import RELEASE_TAG

FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
CANONICAL_GITHUB_REPOSITORY = "neuron7x/KORPUS"
CANONICAL_GITHUB_REPOSITORY_ID = "1332311807"
CANONICAL_GITHUB_OWNER_ID = "206596321"


def _canonical_github_runtime_context() -> bool:
    """Return whether hosted runtime trust came from the protected canonical forge.

    GitHub's OIDC identity binds the repository and workflow, but a verifier sees the
    corresponding runner context first.  Refuse injected trust before cryptographic
    verification unless that context names the canonical repository, a protected main
    or release-tag ref, its exact source SHA, and a workflow loaded from that same ref.
    """
    ref = os.getenv("GITHUB_REF", "")
    ref_name = os.getenv("GITHUB_REF_NAME", "")
    ref_type = os.getenv("GITHUB_REF_TYPE", "")
    branch = ref == "refs/heads/main" and ref_name == "main" and ref_type == "branch"
    tag = ref == f"refs/tags/{RELEASE_TAG}" and ref_name == RELEASE_TAG and ref_type == "tag"
    workflow_ref = os.getenv("GITHUB_WORKFLOW_REF", "")
    workflow_prefix = f"{CANONICAL_GITHUB_REPOSITORY}/.github/workflows/"
    return all(
        (
            os.getenv("GITHUB_ACTIONS") == "true",
            os.getenv("GITHUB_EVENT_NAME") in {"push", "workflow_dispatch"},
            os.getenv("GITHUB_SERVER_URL") == "https://github.com",
            os.getenv("GITHUB_REPOSITORY") == CANONICAL_GITHUB_REPOSITORY,
            os.getenv("GITHUB_REPOSITORY_ID") == CANONICAL_GITHUB_REPOSITORY_ID,
            os.getenv("GITHUB_REPOSITORY_OWNER_ID") == CANONICAL_GITHUB_OWNER_ID,
            os.getenv("GITHUB_REF_PROTECTED") == "true",
            os.getenv("RUNNER_ENVIRONMENT") == "github-hosted",
            os.getenv("GITLAB_CI") != "true",
            branch or tag,
            bool(GIT_SHA.fullmatch(os.getenv("GITHUB_SHA", ""))),
            workflow_ref.startswith(workflow_prefix),
            workflow_ref.endswith(f"@{ref}"),
        )
    )


def trusted_fingerprints(config: Path, field: str, env_name: str) -> set[str]:
    """Load trust roots from repository policy plus externally controlled runtime state.

    Repository defaults stay empty. A protected deployment can inject a pre-admitted
    fingerprint without changing the source tree whose evidence is being judged.
    """
    configured: set[str] = set()
    if config.is_file():
        payload = json.loads(config.read_text(encoding="utf-8"))
        configured = {str(value).strip().lower() for value in payload.get(field, ())}
    injected = {
        value.strip().lower() for value in os.getenv(env_name, "").split(",") if value.strip()
    }
    invalid = sorted(value for value in configured | injected if not FINGERPRINT.fullmatch(value))
    if invalid:
        raise ValueError(f"invalid trusted signer fingerprint(s): {invalid}")
    hosted_ci = os.getenv("CI") == "true" or any(
        os.getenv(name) == "true" for name in ("GITHUB_ACTIONS", "GITLAB_CI")
    )
    if injected and hosted_ci and not _canonical_github_runtime_context():
        raise ValueError(
            "runtime trust roots require a protected canonical GitHub ref, workflow, and SHA"
        )
    return configured | injected
