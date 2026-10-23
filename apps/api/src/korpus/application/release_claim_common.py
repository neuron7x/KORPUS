from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EvidenceContext:
    root: Path
    claim_id: str
    evidence: str
    source_digest: str
    release: str

    @property
    def path(self) -> Path:
        return self.root / self.evidence


def integer(value: object, *, minimum: int = 0) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= minimum


def sha256(value: object) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def provenance_generated_by(payload: dict[str, Any], generator: str) -> bool:
    provenance = payload.get("provenance")
    return bool(
        isinstance(provenance, dict)
        and provenance.get("schema_version") == 1
        and provenance.get("generator") == generator
        and isinstance(provenance.get("generated_at"), str)
        and provenance["generated_at"]
    )
