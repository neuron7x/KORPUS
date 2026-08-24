"""I/O helpers for the PEC research program CLI."""
from __future__ import annotations

import json
from pathlib import Path
from pec_common import sha256_file


def load_optional_report(path: Path | None, key: str) -> tuple[dict, list[dict], str]:
    if path is None:
        return {}, [], ""
    raw = json.loads(path.read_text())
    return raw, list(raw.get(key, [])), sha256_file(path)
