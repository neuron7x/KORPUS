"""Canonical loading and hashing for the bounded-plasticity policy artifact."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from korpus.application.plasticity import AdaptationPolicy

SCHEMA = "korpus.plasticity-policy.v1"


def load_plasticity_policy(path: Path) -> tuple[AdaptationPolicy, str]:
    """Load exactly one supported policy and return its semantic SHA-256."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.pop("schema", None) != SCHEMA:
        raise ValueError("unsupported plasticity policy schema")
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return AdaptationPolicy(**raw), hashlib.sha256(canonical).hexdigest()
