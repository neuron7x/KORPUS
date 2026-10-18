from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

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


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _contains_forbidden_key(value: object) -> bool:
    if isinstance(value, Mapping):
        return bool(FORBIDDEN_KEYS & set(value)) or any(
            _contains_forbidden_key(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


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


def gitlab_delivery_is_inert(config: Mapping[str, Any], policy: Mapping[str, Any]) -> bool:
    jobs = policy.get("allowed_job_sha256")
    if _digest(policy) != POLICY_SHA256 or not isinstance(jobs, Mapping):
        return False
    if (
        _digest(config) != PIPELINE_SHA256
        or set(config) != CONTROL_KEYS | set(jobs)
        or _contains_forbidden_key(config)
    ):
        return False
    hashes_match = all(_digest(config.get(name)) == digest for name, digest in jobs.items())
    return hashes_match and all(_tombstone(config, name) for name in TOMBSTONES)
