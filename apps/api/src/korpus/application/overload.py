from __future__ import annotations

from enum import StrEnum


class OverloadReason(StrEnum):
    SUBJECT_SHARE = "subject_share_exhausted"
    GLOBAL_CAPACITY = "global_capacity_exhausted"


class OverloadedError(RuntimeError):
    def __init__(self, reason: OverloadReason) -> None:
        self.reason = reason
        super().__init__(
            "per-subject capacity exhausted"
            if reason is OverloadReason.SUBJECT_SHARE
            else "answer capacity exhausted"
        )
