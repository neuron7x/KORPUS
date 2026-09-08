"""Межі шлюзу до відправки: кожна відмова власним входом.

`CapabilityGateway.invoke` — це послідовність воріт, і кожні мають свій код відмови.
Код тут не косметика: клієнт за ним вирішує, чи повторювати виклик, а оператор — чи
це його вада, чи провайдерова. Злиті коди роблять обидва рішення неможливими.
Виміряно 08.09.2026: непокритими лишались саме ці ворота.

Фікстури беруться з `test_capability_gateway_invoke`.
"""

from __future__ import annotations

from enum import StrEnum

import pytest
from korpus.application.capability_gateway.adapters import AdapterRegistry
from korpus.application.capability_gateway.audit import InvocationOutcome
from korpus.application.capability_gateway.effects import EffectState, ReconciliationDisposition
from korpus.application.capability_gateway.invoke import CapabilityGateway, _replay_semantics
from korpus.application.capability_gateway.policy import CapabilityPolicyBridge
from korpus.application.capability_gateway.registry import CapabilityRegistry
from korpus.application.capability_gateway.types import (
    CapabilityLifecycle,
    CapabilitySpec,
    IntegrationRequest,
)
from korpus.application.policy import PolicyEngine
from korpus.domain.models import Identity

from apps.api.tests.test_capability_gateway_invoke import (
    _Adapter,
    _Audit,
    _effect_safety,
    _EffectAuthorizer,
    _Egress,
    _gateway,
    _identity,
    _Ledger,
    _request,
    _Schemas,
    _spec,
)

MAPPER_ID = "reference_resource_v1"
ACTION = "integration:reference:action"


def _build(
    *,
    spec: CapabilitySpec | None = None,
    resource_mappers: dict[str, object] | None = None,
    policy: CapabilityPolicyBridge | None = None,
    schemas: object | None = None,
    audit: _Audit | None = None,
) -> tuple[CapabilityGateway, _Adapter, _Audit]:
    declared = spec or _spec()
    adapter = _Adapter()
    adapters = AdapterRegistry()
    adapters.register("internal.reference", "1.0.0", adapter)
    selected_audit = audit or _Audit()
    default_mappers: dict[str, object] = {
        MAPPER_ID: lambda identity, capability, request: (
            f"reference:{request.input['reference_id']}"
        )
    }
    gateway = CapabilityGateway(
        registry=CapabilityRegistry([declared]),
        policy=policy
        or CapabilityPolicyBridge(
            PolicyEngine(),
            action_permissions={ACTION: "answer:read"},
            resource_authorizers={MAPPER_ID: lambda identity, capability, resource: True},
        ),
        adapters=adapters,
        schemas=schemas or _Schemas(),
        resource_mappers=resource_mappers if resource_mappers is not None else default_mappers,
        egress=_Egress(),
        effect_authorizer=_EffectAuthorizer(),
        effects=_Ledger(),
        audit=selected_audit,
        effect_safety=_effect_safety(declared),
    )
    return gateway, adapter, selected_audit


@pytest.mark.parametrize(
    "lifecycle",
    [
        CapabilityLifecycle.DECLARED,
        CapabilityLifecycle.VALIDATED,
        CapabilityLifecycle.DISABLED,
        CapabilityLifecycle.QUARANTINED,
        CapabilityLifecycle.RETIRED,
    ],
)
def test_a_capability_that_is_not_enabled_is_denied_before_dispatch(
    lifecycle: CapabilityLifecycle,
) -> None:
    """Зареєстрована ≠ увімкнена. Код відмови окремий від «невідома»: оператор має
    відрізняти чужий запит від власного вимкненого стану."""
    gateway, adapter, _ = _build(spec=_spec().model_copy(update={"lifecycle": lifecycle}))

    result = gateway.invoke(identity=_identity(), request=_request())

    assert result.outcome is InvocationOutcome.DENIED
    assert result.error_code == "CAPABILITY_DISABLED"
    assert adapter.calls == 0


def test_an_unregistered_resource_mapper_fails_closed_before_authorization() -> None:
    """Спроможність оголосила відображач, якого композиція не дала: питати нема в кого."""
    gateway, adapter, _ = _build(resource_mappers={})

    result = gateway.invoke(identity=_identity(), request=_request())

    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "RESOURCE_MAPPER_UNKNOWN"
    assert adapter.calls == 0


@pytest.mark.parametrize("mapped", ["", "   ", 7, None, b"reference:1"])
def test_a_mapper_that_does_not_return_a_resource_fails_closed(mapped: object) -> None:
    """Порожній або нерядковий ресурс не адресує нічого — авторизувати «нічого» не можна."""
    gateway, adapter, _ = _build(
        resource_mappers={MAPPER_ID: lambda identity, capability, request: mapped}
    )

    result = gateway.invoke(identity=_identity(), request=_request())

    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "RESOURCE_MAPPING_FAILED"
    assert adapter.calls == 0


def test_a_resource_that_cannot_be_canonically_encoded_fails_closed() -> None:
    """Одиночний сурогат проходить `isinstance(str)` і `strip()`, а на дайджесті падає.

    Рядок такої форми природно виникає з декодування `errors="surrogateescape"`, тож
    відображач може повернути його не зловмисно. Раніше це виходило зі шлюзу
    необробленим UnicodeEncodeError.
    """
    gateway, adapter, _ = _build(
        resource_mappers={MAPPER_ID: lambda identity, capability, request: "reference:\ud800"}
    )

    result = gateway.invoke(identity=_identity(), request=_request())

    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "RESOURCE_MAPPING_FAILED"
    assert adapter.calls == 0


def test_an_identity_built_past_validation_stops_before_authorization() -> None:
    """`model_construct` обходить валідатори; шлюз не сміє довіряти формі особи."""
    gateway, adapter, _ = _build()
    identity = Identity.model_construct(subject="reader", roles=frozenset({1, "user"}))

    result = gateway.invoke(identity=identity, request=_request())

    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "INTERNAL_ERROR"
    assert adapter.calls == 0


def test_a_policy_bridge_that_raises_an_unnamed_error_is_policy_unknown() -> None:
    """Політика, що впала, НЕ повернула рішення — а «немає рішення» не є «не заборонено»."""

    class _Erratic(CapabilityPolicyBridge):
        def authorize_resource(self, identity, spec, *, logical_resource):  # type: ignore[no-untyped-def]
            del identity, spec, logical_resource
            raise OSError("policy backend socket closed")

    gateway, adapter, _ = _build(
        policy=_Erratic(
            PolicyEngine(),
            action_permissions={ACTION: "answer:read"},
            resource_authorizers={MAPPER_ID: lambda identity, capability, resource: True},
        )
    )

    result = gateway.invoke(identity=_identity(), request=_request())

    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "POLICY_UNKNOWN"
    assert adapter.calls == 0


def test_a_request_over_the_declared_ceiling_is_rejected() -> None:
    """Стеля запиту належить спроможності; перевищення — вада ЗАПИТУ, не системи."""
    gateway, adapter, audit = _build()
    oversized = IntegrationRequest(
        schema_version="korpus.integration-request.v1",
        capability_id="reference.public.action",
        capability_version="1.0.0",
        input={"reference_id": "x" * 20_000},
    )

    result = gateway.invoke(identity=_identity(), request=oversized)

    assert result.outcome is InvocationOutcome.REJECTED
    assert result.error_code == "INPUT_SCHEMA_INVALID"
    assert adapter.calls == 0
    assert len(audit.calls) == 1


def test_an_input_validator_that_fails_in_an_unnamed_way_is_an_internal_error() -> None:
    """Аварія валідатора — не вирок ЗАПИТУ: клієнт не має правити те, що ціле."""

    class _Exploding:
        def validate(self, schema_id: str, value: object) -> None:
            del value
            if schema_id.endswith("input:v1"):
                raise RuntimeError("validator backend is misconfigured")

    gateway, adapter, _ = _build(schemas=_Exploding())

    result = gateway.invoke(identity=_identity(), request=_request())

    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "INTERNAL_ERROR"
    assert adapter.calls == 0


def test_a_well_formed_invocation_still_succeeds() -> None:
    """Негативний контроль: усі ворота вище карають ФОРМУ, а не сам виклик."""
    gateway, adapter, _ = _build()

    result = gateway.invoke(identity=_identity(), request=_request())

    assert result.outcome is InvocationOutcome.SUCCESS
    assert adapter.calls == 1


class _FutureDisposition(StrEnum):
    """Розпорядження узгодження, додане в майбутньому й НЕ враховане проєкцією повтору."""

    CONFIRMED_PARTIAL = "CONFIRMED_PARTIAL"


def test_a_reconciliation_disposition_nobody_taught_the_replay_is_an_internal_error() -> None:
    """Новий член `ReconciliationDisposition` без правила тут мусить впасти, не провалитись.

    Провал крізь усі гілки повернув би «нічого не відомо» як звичайну відмову, і
    повторний виклик дії, чий наслідок ніхто не назвав, став би дозволеним.
    """
    from apps.api.tests.test_capability_gateway_adapter_result_boundary import _record

    record = _record()
    object.__setattr__(record, "state", EffectState.RECONCILED)
    object.__setattr__(record, "reconciliation_disposition", _FutureDisposition.CONFIRMED_PARTIAL)

    assert _replay_semantics(record) == (InvocationOutcome.FAILED, "INTERNAL_ERROR")


def test_both_declared_dispositions_name_their_own_outcome() -> None:
    """Негативний контроль: правило карає НЕВІДОМЕ розпорядження, не стан RECONCILED."""
    from dataclasses import replace

    from apps.api.tests.test_capability_gateway_adapter_result_boundary import _record

    committed = replace(
        _record(),
        state=EffectState.RECONCILED,
        reconciliation_disposition=ReconciliationDisposition.CONFIRMED_COMMITTED,
        provider_reference="provider:42",
    )
    no_effect = replace(
        _record(),
        state=EffectState.RECONCILED,
        reconciliation_disposition=ReconciliationDisposition.CONFIRMED_NO_EFFECT,
        provider_reference="provider:42",
    )

    assert _replay_semantics(committed) == (
        InvocationOutcome.FAILED,
        "IDEMPOTENT_REPLAY_COMMITTED",
    )
    assert _replay_semantics(no_effect) == (
        InvocationOutcome.FAILED,
        "IDEMPOTENT_REPLAY_KNOWN_NO_EFFECT",
    )


def test_the_shared_gateway_fixture_is_unchanged_by_this_module() -> None:
    """Негативний контроль на фікстуру: локальна композиція не розійшлася зі спільною."""
    gateway, adapter, _, _ = _gateway()

    result = gateway.invoke(identity=_identity(), request=_request())

    assert result.outcome is InvocationOutcome.SUCCESS
    assert adapter.calls == 1


class _FutureEffectState(StrEnum):
    """Стан дії, доданий у майбутньому й НЕ врахований проєкцією повтору."""

    SUSPENDED = "SUSPENDED"


def test_an_effect_state_nobody_taught_the_replay_is_an_internal_error() -> None:
    """Нерозпізнаний стан не сміє провалитись крізь усі гілки як звичайна відмова."""
    from apps.api.tests.test_capability_gateway_adapter_result_boundary import _record

    record = _record()
    object.__setattr__(record, "state", _FutureEffectState.SUSPENDED)

    assert _replay_semantics(record) == (InvocationOutcome.FAILED, "INTERNAL_ERROR")


def test_a_registry_that_fails_in_its_own_declared_family_is_an_internal_error() -> None:
    """Реєстр — теж порт. Його непередбачена відмова не є «спроможність невідома»."""
    from korpus.application.capability_gateway.errors import CapabilityRegistrationError

    class _Failing(CapabilityRegistry):
        def resolve_exact(self, capability_id: str, version: str) -> CapabilitySpec:
            del capability_id, version
            raise CapabilityRegistrationError("registry snapshot is inconsistent")

        def frozen_snapshot(self) -> CapabilityRegistry:
            snapshot = _Failing(self.all_specs())
            snapshot._frozen = True
            return snapshot

    declared = _spec()
    adapter = _Adapter()
    adapters = AdapterRegistry()
    adapters.register("internal.reference", "1.0.0", adapter)
    gateway = CapabilityGateway(
        registry=_Failing([declared]),
        policy=CapabilityPolicyBridge(
            PolicyEngine(),
            action_permissions={ACTION: "answer:read"},
            resource_authorizers={MAPPER_ID: lambda identity, capability, resource: True},
        ),
        adapters=adapters,
        schemas=_Schemas(),
        resource_mappers={
            MAPPER_ID: lambda identity, capability, request: (
                f"reference:{request.input['reference_id']}"
            )
        },
        egress=_Egress(),
        effect_authorizer=_EffectAuthorizer(),
        effects=_Ledger(),
        audit=_Audit(),
        effect_safety=_effect_safety(declared),
    )

    result = gateway.invoke(identity=_identity(), request=_request())

    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "INTERNAL_ERROR"
    assert adapter.calls == 0


def _idempotent_spec() -> CapabilitySpec:
    """Неефектна спроможність, яка все одно вимагає довговічного ключа ідемпотентності."""
    from korpus.application.capability_gateway.types import IdempotencySpec

    return _spec().model_copy(update={"idempotency": IdempotencySpec(required=True)})


def test_a_declared_idempotency_requirement_without_a_key_is_rejected() -> None:
    """Ключ вимагає СПРОМОЖНІСТЬ; без нього повтор не відрізнити від нового виклику.

    Правило стоїть у `validate_request_binding`, тобто ПЕРЕД резервацією: тому код тут
    «вада запиту», а не «потрібна ідемпотентність». Обидва вірні; важливо, що спрацьовує
    ПЕРШИЙ, бо другий уже не побачив би нічого нового.
    """
    gateway, adapter, _ = _build(spec=_idempotent_spec())

    result = gateway.invoke(identity=_identity(), request=_request())

    assert result.outcome is InvocationOutcome.REJECTED
    assert result.error_code == "INPUT_SCHEMA_INVALID"
    assert adapter.calls == 0


def test_an_effectful_capability_composed_without_durable_idempotency_is_rejected() -> None:
    """Жоден допуск не звіряє це під час композиції — вада спливає на першому виклику.

    Ефектна спроможність без обов'язкової ідемпотентності не має чим довести, що повтор
    не подвоїть дію; відмова мусить настати ДО відправки, а не після.
    """
    from korpus.application.capability_gateway.types import EffectClass, IdempotencySpec

    spec = _spec(effect=EffectClass.WRITE_REMOTE).model_copy(
        update={"idempotency": IdempotencySpec(required=False)}
    )
    gateway, adapter, _ = _build(spec=spec)

    result = gateway.invoke(identity=_identity(), request=_request(idempotency_key="idem-1"))

    assert result.outcome is InvocationOutcome.REJECTED
    assert result.error_code == "IDEMPOTENCY_REQUIRED"
    assert adapter.calls == 0


def test_a_key_already_bound_to_another_invocation_is_a_conflict() -> None:
    """Той самий ключ на іншому предметі — не повтор, а зіткнення."""
    from dataclasses import replace as dataclass_replace

    from korpus.application.capability_gateway.effects import EffectReservation

    from apps.api.tests.test_capability_gateway_adapter_result_boundary import _record

    class _Foreign(_Ledger):
        def reserve(self, **kwargs: object) -> EffectReservation:
            record = dataclass_replace(
                _record(),
                subject_id=str(kwargs["subject_id"]),
                idempotency_key=str(kwargs["idempotency_key"]),
                binding_digest="sha256:" + "9" * 64,
            )
            return EffectReservation(record=record, created=False)

    gateway, adapter, _ = _build_with_ledger(_Foreign())

    result = gateway.invoke(identity=_identity(), request=_request(idempotency_key="idem-conflict"))

    assert result.outcome is InvocationOutcome.REJECTED
    assert result.error_code == "IDEMPOTENCY_CONFLICT"
    assert adapter.calls == 0


def test_a_ledger_that_returns_an_unattestable_reservation_is_an_internal_error() -> None:
    """Реєстр відповів, і відповідь не витримала атестації — це вада реєстру, не збій."""

    class _Bogus(_Ledger):
        def reserve(self, **kwargs: object) -> object:
            del kwargs
            return {"created": True}

    gateway, adapter, _ = _build_with_ledger(_Bogus())

    result = gateway.invoke(identity=_identity(), request=_request(idempotency_key="idem-1"))

    assert result.outcome is InvocationOutcome.FAILED
    assert result.error_code == "INTERNAL_ERROR"
    assert adapter.calls == 0


def _build_with_ledger(ledger: object) -> tuple[CapabilityGateway, _Adapter, _Audit]:
    declared = _idempotent_spec()
    adapter = _Adapter()
    adapters = AdapterRegistry()
    adapters.register("internal.reference", "1.0.0", adapter)
    audit = _Audit()
    gateway = CapabilityGateway(
        registry=CapabilityRegistry([declared]),
        policy=CapabilityPolicyBridge(
            PolicyEngine(),
            action_permissions={ACTION: "answer:read"},
            resource_authorizers={MAPPER_ID: lambda identity, capability, resource: True},
        ),
        adapters=adapters,
        schemas=_Schemas(),
        resource_mappers={
            MAPPER_ID: lambda identity, capability, request: (
                f"reference:{request.input['reference_id']}"
            )
        },
        egress=_Egress(),
        effect_authorizer=_EffectAuthorizer(),
        effects=ledger,
        audit=audit,
        effect_safety=_effect_safety(declared),
    )
    return gateway, adapter, audit
