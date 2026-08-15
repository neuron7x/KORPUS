"""Read the release identity from the bytes being signed or verified."""
from __future__ import annotations

import json
from pathlib import Path


def manifest_release(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    release = payload.get("release") if isinstance(payload, dict) else None
    if not isinstance(release, str) or not release:
        raise RuntimeError("signed manifest carries no release identity")
    return release
