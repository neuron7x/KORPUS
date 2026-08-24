from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load_release_identity(root: Path = ROOT) -> dict[str, str]:
    data = json.loads((root / "apps/api/src/korpus/release.json").read_text(encoding="utf-8"))
    required = {"schema", "product", "version", "tag", "artifact_stem", "distribution_artifact"}
    missing = required.difference(data)
    if missing:
        raise RuntimeError(f"release identity missing fields: {sorted(missing)}")
    version, tag = str(data["version"]), str(data["tag"])
    if tag != f"v{version}":
        raise RuntimeError("release identity tag/version mismatch")
    return {str(key): str(value) for key, value in data.items()}


def release_version(root: Path = ROOT) -> str:
    return load_release_identity(root)["version"]


def release_tag(root: Path = ROOT) -> str:
    return load_release_identity(root)["tag"]
