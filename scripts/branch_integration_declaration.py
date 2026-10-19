from __future__ import annotations

import json
from pathlib import Path

CANONICAL_DECLARATION = "config/operations/canonical-state.json"
ACTIVE_REMOTE_ROLES = {"mirror", "integration-source"}


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
