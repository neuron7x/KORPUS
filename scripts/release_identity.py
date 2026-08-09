from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_PATH = ROOT / "apps/api/src/korpus/release.json"

def load_release_identity() -> dict[str, str]:
    data = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))
    required = {"schema", "product", "version", "tag", "artifact_stem"}
    missing = required.difference(data)
    if missing:
        raise RuntimeError(f"release identity missing fields: {sorted(missing)}")
    version = str(data["version"])
    tag = str(data["tag"])
    if tag != f"v{version}":
        raise RuntimeError("release identity tag/version mismatch")
    return {str(k): str(v) for k, v in data.items()}

def release_version() -> str:
    return load_release_identity()["version"]

def release_tag() -> str:
    return load_release_identity()["tag"]
