from __future__ import annotations
from typing import Any


def assessor_identity_valid(evidence: dict[str, Any]) -> bool:
    assessor = evidence.get("assessor")
    if not isinstance(assessor, dict):
        return False
    return (
        isinstance(assessor.get("organization"), str) and bool(assessor.get("organization"))
        and isinstance(assessor.get("assessor_id"), str) and bool(assessor.get("assessor_id"))
        and assessor.get("independent_of_system_owner") is True
    )
