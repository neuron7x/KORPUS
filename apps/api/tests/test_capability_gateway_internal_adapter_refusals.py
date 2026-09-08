"""Внутрішній адаптер вузький НАВМИСНО — і кожне звуження мусить бути пройдене.

`InternalFunctionAdapter` виконує лише серверні детерміністичні читання: провайдер
INTERNAL, ефект READ_LOCAL, доказ NONE або EXECUTION_ONLY. Три відмови, які це
тримають, лишались непройденими (виміряно 08.09.2026), а звуження, якого ніхто не
перевіряв, не відрізняється від знятого.
"""

from __future__ import annotations

import pytest
from korpus.application.capability_gateway.adapters import AdapterExecutionFailed
from korpus.application.capability_gateway.types import (
    EffectClass,
    EvidenceProfile,
    ProviderType,
)
from korpus.infrastructure.integrations.internal import InternalFunctionAdapter

from apps.api.tests.test_capability_gateway_internal_adapter import _context, _request, _spec


def _adapter() -> InternalFunctionAdapter:
    return InternalFunctionAdapter(lambda payload, resource: {"value": "ok"})


def _run(spec) -> object:
    return _adapter().execute(
        spec=spec, request=_request(), context=_context(), logical_resource="reference/alpha"
    )


def test_a_remote_provider_is_refused() -> None:
    """Адаптер без мережі не виконує спроможність, оголошену як віддалену."""
    with pytest.raises(AdapterExecutionFailed, match="remote provider"):
        _run(_spec().model_copy(update={"provider_type": ProviderType.HTTP}))


def test_an_effectful_capability_is_refused() -> None:
    """Читальний адаптер не виконує дію з наслідком, хоч би що казав виклик."""
    with pytest.raises(AdapterExecutionFailed, match="read-only"):
        _run(_spec().model_copy(update={"effect_class": EffectClass.WRITE_REMOTE}))


def test_evidence_none_profile_yields_no_envelope() -> None:
    """Профіль NONE — ВІДСУТНІЙ доказ, а не слабший: конверт не вигадується."""
    result = _run(_spec(evidence=EvidenceProfile.NONE))
    assert result.evidence is None  # type: ignore[attr-defined]


def test_execution_only_profile_yields_a_reproducible_internal_envelope() -> None:
    """Негативний контроль: правило карає ЧУЖИЙ профіль, а не сам доказ."""
    result = _run(_spec(evidence=EvidenceProfile.EXECUTION_ONLY))
    assert result.evidence is not None  # type: ignore[attr-defined]
    assert result.evidence.reproducible is True  # type: ignore[attr-defined]
