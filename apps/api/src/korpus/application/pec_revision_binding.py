from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

_HEX = frozenset("0123456789abcdef")


def _sha256(value: object, field: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(ch not in _HEX for ch in text):
        raise ValueError(f"{field} must be a lowercase sha256 digest")
    return text


def _required(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


@dataclass(frozen=True)
class RevisionBinding:
    release: str
    revision: str
    profile: str
    phase: str
    environment_class: str
    training_receipt_sha256: str

    @classmethod
    def from_mapping(
        cls, payload: Mapping[str, object], *, expected_release: str
    ) -> RevisionBinding:
        release = _required(payload.get("release"), "release")
        if release != expected_release:
            raise ValueError("release binding mismatch")
        environment = _required(payload.get("environment_class"), "environment_class")
        if environment != "PRODUCTION":
            raise ValueError("production PEC evidence requires environment_class=PRODUCTION")
        return cls(
            release=release,
            revision=_required(payload.get("revision"), "revision"),
            profile=_required(payload.get("profile"), "profile"),
            phase=_required(payload.get("phase"), "phase"),
            environment_class=environment,
            training_receipt_sha256=_sha256(
                payload.get("training_receipt_sha256"), "training_receipt_sha256"
            ),
        )
