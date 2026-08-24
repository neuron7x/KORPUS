from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class TrainingLineageVerdict:
    valid: bool
    failures: tuple[str, ...]


def validate_training_lineage(
    receipt: Mapping[str, object],
    *,
    release: str,
    profile: str,
    source_revision: str,
    dataset_sha256: str,
) -> TrainingLineageVerdict:
    checks = {
        "release": str(receipt.get("release", "")) == release,
        "profile": str(receipt.get("profile", "")) == profile,
        "source_revision": str(receipt.get("source_revision", "")) == source_revision,
        "dataset_sha256": str(receipt.get("dataset_sha256", "")) == dataset_sha256,
        "receipt_sha256": len(str(receipt.get("receipt_sha256", ""))) == 64
        and all(ch in "0123456789abcdef" for ch in str(receipt.get("receipt_sha256", ""))),
    }
    failures = tuple(name for name, ok in checks.items() if not ok)
    return TrainingLineageVerdict(not failures, failures)
