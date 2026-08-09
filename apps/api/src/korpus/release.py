"""Machine-readable release identity accessor.

`release.json` is the authoritative current-release identity. Code imports this module;
release tooling reads the same JSON rather than carrying independent defaults.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Final

_RELEASE_PATH = Path(__file__).with_name("release.json")
_RELEASE = json.loads(_RELEASE_PATH.read_text(encoding="utf-8"))
RELEASE_VERSION: Final[str] = str(_RELEASE["version"])
RELEASE_TAG: Final[str] = str(_RELEASE["tag"])
ARTIFACT_STEM: Final[str] = str(_RELEASE["artifact_stem"])

def release_identity() -> dict[str, str]:
    return {str(k): str(v) for k, v in _RELEASE.items()}
