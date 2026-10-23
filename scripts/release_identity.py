from __future__ import annotations

import json
from pathlib import Path

from package_identity_contract import valid_release_identity

ROOT = Path(__file__).resolve().parents[1]


def load_release_identity(root: Path = ROOT) -> dict[str, str]:
    data = json.loads((root / "apps/api/src/korpus/release.json").read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not valid_release_identity(data):
        raise RuntimeError("invalid canonical release identity")
    return {str(key): str(value) for key, value in data.items()}


def release_version(root: Path = ROOT) -> str:
    return load_release_identity(root)["version"]


def release_tag(root: Path = ROOT) -> str:
    return load_release_identity(root)["tag"]
