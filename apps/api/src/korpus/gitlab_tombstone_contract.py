from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

CONTROL_KEYS = {"workflow", "default", "stages", "variables"}
FORBIDDEN_KEYS = {"include", "trigger", "id_tokens", "identity", "environment", "resource_group"}
PIPELINE_SHA256 = "9e6c510b72cf94c3b1d92d32fb1ec595deebf418301911a6c7395773b291db80"
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


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _contains_forbidden_key(value: object) -> bool:
    if isinstance(value, Mapping):
        return bool(FORBIDDEN_KEYS & set(value)) or any(
            _contains_forbidden_key(item) for item in value.values()
        )
    return isinstance(value, list) and any(_contains_forbidden_key(item) for item in value)


def gitlab_tombstone(config: Mapping[str, Any], name: str) -> bool:
    stage, marker = TOMBSTONES[name]
    job = config.get(name)
    return bool(
        isinstance(job, Mapping)
        and set(job) == {"stage", "rules", "script"}
        and job.get("stage") == stage
        and job.get("rules") == [{"when": "never"}]
        and job.get("script") == [marker, "exit 1"]
    )


def gitlab_pipeline_globally_disabled(config: Mapping[str, Any]) -> bool:
    return config.get("workflow") == {"rules": [{"when": "never"}]}


def gitlab_delivery_is_inert(config: Mapping[str, Any], policy: Mapping[str, Any]) -> bool:
    jobs = policy.get("allowed_job_sha256")
    if not isinstance(jobs, Mapping):
        return False
    admitted = (
        _digest(policy) == POLICY_SHA256
        and _digest(config) == PIPELINE_SHA256
        and set(config) == CONTROL_KEYS | set(jobs)
        and not _contains_forbidden_key(config)
    )
    return bool(
        admitted
        and gitlab_pipeline_globally_disabled(config)
        and all(_digest(config.get(name)) == digest for name, digest in jobs.items())
        and all(gitlab_tombstone(config, name) for name in TOMBSTONES)
    )
