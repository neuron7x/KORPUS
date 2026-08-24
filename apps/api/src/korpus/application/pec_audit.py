from __future__ import annotations

from korpus.domain.models import RetrievedEvidence


def pec_audit_payload(
    trace: dict[str, object] | None,
    retrieved: list[RetrievedEvidence],
) -> dict[str, object] | None:
    if trace is None:
        return None
    return {
        **trace,
        "final_evidence_fingerprints": [item.span.text_hash for item in retrieved],
    }
