from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

CONTROL_KEYS = {"workflow", "default", "stages", "variables"}
FORBIDDEN_KEYS = {"include", "trigger", "id_tokens", "identity", "environment", "resource_group"}
PIPELINE_SHA256 = "3cc3ebfe1c55b41d1d849347e3ab7e8b9ff58ad769c6bbf8b8a582fca06d87fd"
POLICY_SHA256 = "b4732c220a4d75e71265cef84f8d1b94c9f502ad8070871097df847303532f8d"
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
