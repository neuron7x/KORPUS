from __future__ import annotations

import json
import os
import re
from pathlib import Path

FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


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
    if (
        injected
        and os.getenv("GITLAB_CI") == "true"
        and os.getenv("CI_COMMIT_REF_PROTECTED") != "true"
    ):
        raise ValueError("runtime trust roots are forbidden on an unprotected GitLab ref")
    return configured | injected
