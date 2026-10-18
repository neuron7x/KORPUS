from __future__ import annotations

import json
import os
import re
from pathlib import Path

from korpus.application.github_release_context import github_release_context_mismatches
from korpus.release import RELEASE_TAG

FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


def _configured_fingerprints(config: Path, field: str) -> set[str]:
    if not config.is_file():
        return set()
    payload = json.loads(config.read_text(encoding="utf-8"))
    return {str(value).strip().lower() for value in payload.get(field, ())}


def _hosted_ci() -> bool:
    return "true" in {os.getenv(name) for name in ("CI", "GITHUB_ACTIONS", "GITLAB_CI")}


def trusted_fingerprints(config: Path, field: str, env_name: str) -> set[str]:
    configured = _configured_fingerprints(config, field)
    injected = {
        value.strip().lower() for value in os.getenv(env_name, "").split(",") if value.strip()
    }
    invalid = sorted(value for value in configured | injected if not FINGERPRINT.fullmatch(value))
    if invalid:
        raise ValueError(f"invalid trusted signer fingerprint(s): {invalid}")
    if injected and _hosted_ci() and github_release_context_mismatches(os.environ, RELEASE_TAG):
        raise ValueError(
            "runtime trust roots require a protected canonical GitHub ref, workflow, and SHA"
        )
    return configured | injected
