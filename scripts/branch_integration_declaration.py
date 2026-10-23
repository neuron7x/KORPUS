from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

CANONICAL_DECLARATION = "config/operations/canonical-state.json"
ACTIVE_REMOTE_ROLES = {"mirror", "integration-source"}
LOCAL_BRANCH_REF = re.compile(r"refs/heads/(?P<branch>.+)")
INVALID_REF_CHAR = re.compile(r"[\x00-\x20\x7f~^:?*\[\\]")


def integration_remotes(root: Path) -> dict[str, str] | None:
    """Declared names label findings; declared URLs are the live authority."""
    try:
        payload = json.loads((root / CANONICAL_DECLARATION).read_text(encoding="utf-8"))
        publications = payload["publications"]
    except (OSError, json.JSONDecodeError, KeyError):
        return None
    if not isinstance(publications, list):
        return None
    remotes = {
        item["remote"]: item["url"]
        for item in publications
        if isinstance(item, dict)
        and item.get("role") in ACTIVE_REMOTE_ROLES
        and isinstance(item.get("remote"), str)
        and item["remote"].strip()
        and isinstance(item.get("url"), str)
        and item["url"].strip()
    }
    return remotes or None


def convergence_candidate(registry: dict[str, Any]) -> str | None:
    """Return the one explicitly declared local candidate branch, if exact."""
    ref = registry.get("convergence_candidate_ref")
    if not isinstance(ref, str):
        return None
    match = LOCAL_BRANCH_REF.fullmatch(ref)
    if match is None:
        return None
    branch = match.group("branch")
    components = branch.split("/")
    invalid = (
        INVALID_REF_CHAR.search(branch) is not None
        or branch in {"@", "."}
        or branch.startswith("-")
        or branch.endswith(".")
        or ".." in branch
        or "@{" in branch
        or any(not part or part.startswith(".") or part.endswith(".lock") for part in components)
    )
    if invalid:
        return None
    return branch
