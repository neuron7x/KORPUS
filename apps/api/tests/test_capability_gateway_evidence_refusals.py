"""Кожна відмова прив'язки доказу — окремим входом.

`validate_evidence` — це місце, де доказ спроможності або прив'язується до ЦЬОГО
виклику, або не приймається. Виміряно 08.09.2026 у гілковому покритті: 16 непокритих
ребер, і всі вони — відмови. Шлях відмови, який ніхто не проходив, не доведений: він
однаково виглядає і коли працює, і коли його зняли.

Фікстури беруться з `test_capability_gateway_adapters_evidence`, а не пишуться вдруге:
друга копія конверта розійшлася б із першою мовчки.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from korpus.application.capability_gateway.errors import CapabilityContractError
from korpus.application.capability_gateway.evidence import (
    CapabilityEvidenceBindingMismatch,
    CapabilityEvidenceStale,
    EvidenceStatus,
    ProvenanceKind,
    validate_evidence,
)
from korpus.application.capability_gateway.types import EvidenceProfile

from apps.api.tests.test_capability_gateway_adapters_evidence import (
    _context,
    _evidence,
    _spec,
)

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
OUTPUT = {"value": "ok"}


def _valid(spec, context, **kwargs):
    return _evidence(spec=spec, context=context, output=OUTPUT, observed_at=NOW, **kwargs)


def _check(envelope, *, spec=None, context=None, at=NOW):
    spec = spec if spec is not None else _spec()
    validate_evidence(
        spec=spec,
        context=context if context is not None else _context(NOW),
        output=OUTPUT,
        evidence=envelope,
        evaluated_at=at,
    )


def test_a_valid_envelope_is_accepted() -> None:
    """Позитивний бік: без нього кожна відмова нижче була б відмовою про все підряд."""
    spec, context = _spec(), _context(NOW)
    _check(_valid(spec, context), spec=spec, context=context)


def test_status_other_than_valid_is_refused() -> None:
    spec, context = _spec(), _context(NOW)
    envelope = _valid(spec, context).model_copy(update={"status": EvidenceStatus.UNKNOWN})
    with pytest.raises(CapabilityContractError):
        _check(envelope, spec=spec, context=context)


def test_a_naive_observation_timestamp_is_refused() -> None:
    """Без часової зони «раніше» і «пізніше» не визначені — порівнювати нема чого."""
    spec, context = _spec(), _context(NOW)
    envelope = _valid(spec, context).model_copy(update={"observed_at": NOW.replace(tzinfo=None)})
    with pytest.raises(CapabilityContractError):
        _check(envelope, spec=spec, context=context)


def test_an_observation_in_the_future_is_refused() -> None:
    spec, context = _spec(), _context(NOW)
    envelope = _evidence(
        spec=spec, context=context, output=OUTPUT, observed_at=NOW + timedelta(minutes=5)
    )
    with pytest.raises(CapabilityContractError):
        _check(envelope, spec=spec, context=context)


def test_a_naive_expiry_is_refused() -> None:
    spec, context = _spec(), _context(NOW)
    envelope = _valid(spec, context).model_copy(
        update={"expires_at": (NOW + timedelta(minutes=5)).replace(tzinfo=None)}
    )
    with pytest.raises(CapabilityContractError):
        _check(envelope, spec=spec, context=context)


def test_expired_evidence_is_refused() -> None:
    spec, context = _spec(), _context(NOW)
    envelope = _valid(spec, context).model_copy(update={"expires_at": NOW + timedelta(seconds=1)})
    with pytest.raises(CapabilityEvidenceStale):
        _check(envelope, spec=spec, context=context, at=NOW + timedelta(seconds=2))


def test_an_expiry_still_ahead_is_accepted() -> None:
    """Негативний контроль до строку: правило карає ПРОСТРОЧЕННЯ, не наявність строку."""
    spec, context = _spec(), _context(NOW)
    envelope = _valid(spec, context).model_copy(update={"expires_at": NOW + timedelta(hours=1)})
    _check(envelope, spec=spec, context=context)


def test_evidence_bound_to_another_invocation_is_refused() -> None:
    spec, context = _spec(), _context(NOW)
    other = _context(NOW).model_copy(update={"invocation_id": uuid4()})
    envelope = _valid(spec, other)
    with pytest.raises(CapabilityEvidenceBindingMismatch):
        _check(envelope, spec=spec, context=context)


def test_evidence_bound_to_another_capability_is_refused() -> None:
    spec, context = _spec(), _context(NOW)
    envelope = _valid(spec, context)
    envelope = envelope.model_copy(
        update={"binding": envelope.binding.model_copy(update={"capability_version": "9.9.9"})}
    )
    with pytest.raises(CapabilityEvidenceBindingMismatch):
        _check(envelope, spec=spec, context=context)


def test_evidence_bound_to_another_adapter_is_refused() -> None:
    spec, context = _spec(), _context(NOW)
    envelope = _valid(spec, context)
    envelope = envelope.model_copy(
        update={"binding": envelope.binding.model_copy(update={"adapter_version": "0.0.1"})}
    )
    with pytest.raises(CapabilityEvidenceBindingMismatch):
        _check(envelope, spec=spec, context=context)


def test_provider_provenance_of_the_wrong_kind_is_refused() -> None:
    spec, context = _spec(EvidenceProfile.PROVIDER_PROVENANCE), _context(NOW)
    envelope = _valid(spec, context, kind=ProvenanceKind.SOURCE_EVIDENCE)
    with pytest.raises(CapabilityContractError):
        _check(envelope, spec=spec, context=context)


def test_factual_profile_requires_source_evidence_kind() -> None:
    spec, context = _spec(EvidenceProfile.FACTUAL_EVIDENCE), _context(NOW)
    envelope = _valid(spec, context, kind=ProvenanceKind.REMOTE_RESPONSE)
    with pytest.raises(CapabilityContractError):
        _check(envelope, spec=spec, context=context)


def test_factual_profile_of_the_right_kind_is_accepted() -> None:
    """Негативний контроль до профілю: правило карає НЕ ТОЙ рід, не сам профіль."""
    spec, context = _spec(EvidenceProfile.FACTUAL_EVIDENCE), _context(NOW)
    _check(
        _valid(spec, context, kind=ProvenanceKind.SOURCE_EVIDENCE),
        spec=spec,
        context=context,
    )


def test_provider_provenance_without_a_source_reference_is_refused() -> None:
    """Провенанс без посилання — твердження про походження, яке нікуди не веде."""
    spec, context = _spec(EvidenceProfile.PROVIDER_PROVENANCE), _context(NOW)
    envelope = _valid(spec, context)
    envelope = envelope.model_copy(
        update={"provenance": envelope.provenance.model_copy(update={"source_refs": []})}
    )
    with pytest.raises(CapabilityContractError):
        _check(envelope, spec=spec, context=context)


def test_factual_evidence_without_source_references_is_refused() -> None:
    spec, context = _spec(EvidenceProfile.FACTUAL_EVIDENCE), _context(NOW)
    envelope = _valid(spec, context, kind=ProvenanceKind.SOURCE_EVIDENCE)
    envelope = envelope.model_copy(
        update={"provenance": envelope.provenance.model_copy(update={"source_refs": []})}
    )
    with pytest.raises(CapabilityContractError):
        _check(envelope, spec=spec, context=context)


def test_signed_receipt_profile_refuses_unsigned_provenance() -> None:
    spec, context = _spec(EvidenceProfile.SIGNED_RECEIPT), _context(NOW)
    envelope = _valid(spec, context, kind=ProvenanceKind.REMOTE_RESPONSE, signature_ref="sig:1")
    with pytest.raises(CapabilityContractError):
        _check(envelope, spec=spec, context=context)


def test_signed_receipt_profile_refuses_a_missing_signature_reference() -> None:
    spec, context = _spec(EvidenceProfile.SIGNED_RECEIPT), _context(NOW)
    envelope = _valid(spec, context, kind=ProvenanceKind.SIGNED_RECEIPT, signature_ref=None)
    with pytest.raises(CapabilityContractError):
        _check(envelope, spec=spec, context=context)


def test_a_complete_signed_receipt_is_accepted() -> None:
    """Негативний контроль: правило карає БРАК підпису, а не профіль підпису."""
    spec, context = _spec(EvidenceProfile.SIGNED_RECEIPT), _context(NOW)
    _check(
        _valid(spec, context, kind=ProvenanceKind.SIGNED_RECEIPT, signature_ref="sig:1"),
        spec=spec,
        context=context,
    )
