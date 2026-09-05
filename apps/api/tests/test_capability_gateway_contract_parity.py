from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from korpus.application.capability_gateway.audit import InvocationOutcome
from korpus.application.capability_gateway.evidence import (
    EvidenceBinding,
    EvidenceEnvelope,
    EvidenceProvenance,
    EvidenceStatus,
    ProvenanceKind,
)
from korpus.application.capability_gateway.result import IntegrationResult
from korpus.application.capability_gateway.types import (
    ActorType,
    InvocationActor,
    InvocationContext,
)

ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = ROOT / "docs/proposals/korpus-capability-gateway-v1/CONTRACTS"
CAPABILITY_SCHEMA = CONTRACTS / "capability-spec.schema.json"
EVIDENCE_SCHEMA = CONTRACTS / "evidence-envelope.schema.json"
RESULT_SCHEMA = CONTRACTS / "integration-result.schema.json"


def _schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _capability_schema() -> dict[str, Any]:
    return _schema(CAPABILITY_SCHEMA)


def _evidence_schema() -> dict[str, Any]:
    return _schema(EVIDENCE_SCHEMA)


def _result_schema() -> dict[str, Any]:
    return _schema(RESULT_SCHEMA)


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


def test_evidence_binding_scalar_limits_match_runtime_model() -> None:
    binding = _evidence_schema()["properties"]["binding"]["properties"]

    assert binding["capability_id"]["minLength"] == 1
    assert binding["capability_id"]["maxLength"] == 128
    assert binding["capability_version"]["minLength"] == 1
    assert binding["capability_version"]["maxLength"] == 64
    assert binding["adapter_id"]["minLength"] == 1
    assert binding["adapter_id"]["maxLength"] == 128
    assert binding["adapter_version"]["minLength"] == 1
    assert binding["adapter_version"]["maxLength"] == 64


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


def test_capability_spec_scalar_limits_match_runtime_model() -> None:
    properties = _capability_schema()["properties"]

    assert properties["version"]["maxLength"] == 64
    assert properties["input_schema_id"]["maxLength"] == 512
    assert properties["output_schema_id"]["maxLength"] == 512
    assert properties["evidence"]["properties"]["bind_output_digest"]["default"] is True


def test_capability_spec_cross_field_rules_match_runtime_validator() -> None:
    rules = _capability_schema()["allOf"]
    assert isinstance(rules, list)
    assert len(rules) == 7

    effectful = {"WRITE_REMOTE", "TRANSACTIONAL_SIDE_EFFECT", "PRIVILEGED_ADMIN"}
    assert set(rules[0]["if"]["properties"]["effect_class"]["enum"]) == effectful
    assert (
        rules[0]["then"]["properties"]["idempotency"]["properties"]["required"]["const"]
        is True
    )

    assert set(rules[1]["if"]["properties"]["effect_class"]["enum"]) == effectful
    assert (
        rules[1]["then"]["properties"]["authorization"]["properties"]
        ["requires_explicit_effect_authorization"]["const"]
        is True
    )
    assert (
        "requires_explicit_effect_authorization"
        in rules[1]["then"]["properties"]["authorization"]["required"]
    )

    assert (
        rules[2]["if"]["properties"]["authorization"]["properties"]
        ["requires_explicit_effect_authorization"]["const"]
        is True
    )
    assert set(rules[2]["then"]["properties"]["effect_class"]["enum"]) == effectful

    assert (
        rules[3]["if"]["properties"]["idempotency"]["properties"]
        ["provider_key_forwarding"]["const"]
        is True
    )
    assert (
        rules[3]["then"]["properties"]["idempotency"]["properties"]["required"]["const"]
        is True
    )

    assert rules[4]["if"]["properties"]["retry"]["properties"]["max_attempts"]["minimum"] == 2
    assert (
        rules[4]["then"]["properties"]["retry"]["properties"]["only_safe_errors"]["const"]
        is True
    )

    assert set(rules[5]["if"]["properties"]["effect_class"]["enum"]) == effectful
    assert rules[5]["if"]["properties"]["retry"]["properties"]["max_attempts"]["minimum"] == 2
    assert (
        rules[5]["then"]["properties"]["idempotency"]["properties"]
        ["provider_key_forwarding"]["const"]
        is True
    )
    assert "provider_key_forwarding" in rules[5]["then"]["properties"]["idempotency"]["required"]

    evidence_profiles = {
        "EXECUTION_ONLY",
        "PROVIDER_PROVENANCE",
        "FACTUAL_EVIDENCE",
        "SIGNED_RECEIPT",
    }
    assert set(
        rules[6]["if"]["properties"]["evidence"]["properties"]["profile"]["enum"]
    ) == evidence_profiles
    assert (
        rules[6]["then"]["properties"]["evidence"]["properties"]
        ["bind_output_digest"]["const"]
        is True
    )


def test_integration_result_contract_encodes_runtime_returnability_invariants() -> None:
    contract = _result_schema()
    conditionals = contract["allOf"]

    assert isinstance(conditionals, list)
    assert len(conditionals) == 1
    branch = conditionals[0]
    assert branch["if"]["properties"]["outcome"]["const"] == "SUCCESS"

    success = branch["then"]["properties"]
    assert success["audit_record_id"]["type"] == "string"
    assert success["audit_record_id"]["minLength"] == 1
    assert success["error_code"]["type"] == "null"

    failure = branch["else"]
    assert "error_code" in failure["required"]
    assert failure["properties"]["output"]["type"] == "null"
    assert failure["properties"]["evidence"]["type"] == "null"
    assert failure["properties"]["error_code"]["type"] == "string"


def test_runtime_result_rejects_success_without_persisted_audit_identity() -> None:
    with pytest.raises(ValidationError, match="persisted audit identity"):
        IntegrationResult(
            invocation_id=uuid4(),
            outcome=InvocationOutcome.SUCCESS,
            output={"value": "ok"},
        )


def test_runtime_result_rejects_non_success_provider_payload() -> None:
    with pytest.raises(ValidationError, match="cannot expose output or evidence"):
        IntegrationResult(
            invocation_id=uuid4(),
            outcome=InvocationOutcome.DENIED,
            output={"sensitive": "provider-output"},
            error_code="POLICY_DENIED",
        )
