from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from korpus.application.capability_gateway.evidence import (
    EvidenceBinding,
    EvidenceEnvelope,
    EvidenceProvenance,
    EvidenceStatus,
    ProvenanceKind,
)
from korpus.application.capability_gateway.types import (
    ActorType,
    InvocationActor,
    InvocationContext,
)

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_SCHEMA = (
    ROOT / "docs/proposals/korpus-capability-gateway-v1/CONTRACTS/evidence-envelope.schema.json"
)


def _evidence_schema() -> dict[str, Any]:
    return json.loads(EVIDENCE_SCHEMA.read_text(encoding="utf-8"))


def _binding() -> EvidenceBinding:
    return EvidenceBinding(
        invocation_id=uuid4(),
        capability_id="reference.contract.read",
        capability_version="1.0.0",
        adapter_id="internal.contract",
        adapter_version="1.0.0",
        output_digest="sha256:" + "0" * 64,
    )


def test_runtime_source_ref_limit_matches_frozen_evidence_contract() -> None:
    contract = _evidence_schema()
    limit = contract["properties"]["provenance"]["properties"]["source_refs"]["items"][
        "maxLength"
    ]
    assert limit == 1024

    accepted = EvidenceProvenance(
        kind=ProvenanceKind.SOURCE_EVIDENCE,
        source_refs=["x" * limit],
    )
    assert len(accepted.source_refs[0]) == limit

    with pytest.raises(ValidationError):
        EvidenceProvenance(
            kind=ProvenanceKind.SOURCE_EVIDENCE,
            source_refs=["x" * (limit + 1)],
        )


def test_evidence_date_time_contract_rejects_naive_observation() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        EvidenceEnvelope(
            schema_version="korpus.evidence-envelope.v1",
            status=EvidenceStatus.VALID,
            binding=_binding(),
            provenance=EvidenceProvenance(
                kind=ProvenanceKind.REMOTE_RESPONSE,
                source_refs=["provider:response:1"],
            ),
            observed_at=datetime(2026, 9, 4, 15, 0),
        )


def test_evidence_date_time_contract_rejects_naive_expiry() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        EvidenceEnvelope(
            schema_version="korpus.evidence-envelope.v1",
            status=EvidenceStatus.VALID,
            binding=_binding(),
            provenance=EvidenceProvenance(
                kind=ProvenanceKind.REMOTE_RESPONSE,
                source_refs=["provider:response:1"],
            ),
            observed_at=datetime(2026, 9, 4, 15, 0, tzinfo=UTC),
            expires_at=datetime(2026, 9, 4, 15, 5),
        )


def test_invocation_context_date_time_contract_rejects_naive_request_time() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        InvocationContext(
            schema_version="korpus.invocation-context.v1",
            invocation_id=uuid4(),
            actor=InvocationActor(actor_type=ActorType.USER, subject_id="reader"),
            request_time=datetime(2026, 9, 4, 15, 0),
            service_release="0.9.7",
            policy_context_digest="sha256:" + "0" * 64,
        )
