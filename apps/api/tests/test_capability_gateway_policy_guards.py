"""Сторожі впорскуваних портів політики — кожен окремим входом.

`CapabilityPolicyBridge` стоїть між керованою спроможністю і канонічною політикою.
Усе, що в нього кладуть, приходить ЗЗОВНІ: карта дій, карта авторизаторів ресурсу,
самі авторизатори. Виміряно 08.09.2026: шість непокритих гілок, і всі — саме ці
перевірки. Сторож, якого ніхто не проходив, не доведений: він однаково виглядає і
коли працює, і коли його зняли.

Фікстури беруться з `test_capability_gateway_port_return_attestation`.
"""

from __future__ import annotations

import pytest
from korpus.application.capability_gateway.errors import CapabilityPolicyIndeterminate
from korpus.application.capability_gateway.policy import CapabilityPolicyBridge
from korpus.application.policy import PolicyEngine

from apps.api.tests.test_capability_gateway_port_return_attestation import _identity, _spec

ACTION = "integration:reference:read"
PERMISSION = "answer:read"


def _bridge(**kwargs: object) -> CapabilityPolicyBridge:
    options: dict[str, object] = {
        "action_permissions": {ACTION: PERMISSION},
        "resource_authorizers": {"reference_resource_v1": lambda i, s, r: True},
    }
    options.update(kwargs)
    return CapabilityPolicyBridge(PolicyEngine(), **options)  # type: ignore[arg-type]


def test_an_empty_action_name_is_refused_at_composition() -> None:
    """Порожня дія відображається в дозвіл, якого ніхто не питав."""
    with pytest.raises(ValueError, match="empty action"):
        _bridge(action_permissions={"   ": PERMISSION})


def test_an_unknown_permission_is_refused_at_composition() -> None:
    """Дозвіл поза канонічним переліком — не «інший дозвіл», а невідомий."""
    with pytest.raises(ValueError):
        _bridge(action_permissions={ACTION: "answer:invent"})


def test_an_empty_resource_mapper_id_is_refused_at_composition() -> None:
    with pytest.raises(ValueError, match="empty mapper id"):
        _bridge(resource_authorizers={"  ": lambda i, s, r: True})


def test_a_resource_authorizer_that_is_not_callable_is_refused_at_composition() -> None:
    """Не-виклик у карті авторизаторів упав би вже в рантаймі, під час рішення."""
    with pytest.raises(ValueError, match="not callable"):
        _bridge(resource_authorizers={"reference_resource_v1": "yes"})


def test_an_empty_logical_resource_is_indeterminate() -> None:
    """Порожній ресурс не адресує нічого; «дозволено на нічому» — не рішення."""
    bridge = _bridge()
    with pytest.raises(CapabilityPolicyIndeterminate, match="logical resource is empty"):
        bridge.authorize_resource(_identity(), _spec(), logical_resource="   ")


def test_an_unregistered_resource_mapper_is_indeterminate() -> None:
    bridge = _bridge(resource_authorizers={})
    with pytest.raises(CapabilityPolicyIndeterminate, match="not registered"):
        bridge.authorize_resource(_identity(), _spec(), logical_resource="reference:1")


def test_a_non_boolean_resource_decision_is_indeterminate() -> None:
    """«Схоже на істину» — не дозвіл. Тільки літеральний `True` дозволяє."""
    bridge = _bridge(resource_authorizers={"reference_resource_v1": lambda i, s, r: 1})
    with pytest.raises(CapabilityPolicyIndeterminate, match="non-boolean"):
        bridge.authorize_resource(_identity(), _spec(), logical_resource="reference:1")


def test_a_resource_authorizer_that_raises_is_indeterminate() -> None:
    """Авторизатор, що впав, не дав рішення. «Немає рішення» ніколи не «не заборонено»."""

    def broken(identity: object, spec: object, resource: str) -> bool:
        raise OSError("resource backend unavailable")

    bridge = _bridge(resource_authorizers={"reference_resource_v1": broken})
    with pytest.raises(CapabilityPolicyIndeterminate, match="could not decide"):
        bridge.authorize_resource(_identity(), _spec(), logical_resource="reference:1")


def test_a_registered_callable_returning_true_is_accepted() -> None:
    """Негативний контроль: сторожі карають негідний вхід, а не сам шлях."""
    decision = _bridge().authorize_resource(_identity(), _spec(), logical_resource="reference:1")
    assert decision.allowed is True


class _BrokenEngine:
    """Канонічна політика, що падає не своєю помилкою."""

    def require(self, identity: object, permission: str) -> None:
        del identity, permission
        raise RuntimeError("policy backend is unreachable")


class _SilentEngine:
    """Політика, що ПОВЕРТАЄ замість того, щоб кинути — тобто не вирішила нічого."""

    def require(self, identity: object, permission: str) -> object:
        del identity, permission
        return "allowed"


def test_a_policy_backend_failure_is_indeterminate_not_an_allow() -> None:
    """Помилка інфраструктури не є дозволом і не є відмовою — вона третій стан."""
    bridge = CapabilityPolicyBridge(
        _BrokenEngine(),  # type: ignore[arg-type]
        action_permissions={ACTION: PERMISSION},
        resource_authorizers={"reference_resource_v1": lambda i, s, r: True},
    )

    with pytest.raises(CapabilityPolicyIndeterminate, match="could not decide"):
        bridge.authorize(_identity(), _spec())


def test_a_policy_that_returns_instead_of_raising_is_indeterminate() -> None:
    """`require` оголошений `-> None`; будь-яке повернення означає інший контракт."""
    bridge = CapabilityPolicyBridge(
        _SilentEngine(),  # type: ignore[arg-type]
        action_permissions={ACTION: PERMISSION},
        resource_authorizers={"reference_resource_v1": lambda i, s, r: True},
    )

    with pytest.raises(CapabilityPolicyIndeterminate, match="non-None authorization sentinel"):
        bridge.authorize(_identity(), _spec())


class _ForgingBridge(CapabilityPolicyBridge):
    """Підклас, чий `authorize` повертає не рішення — перевіряє, чи довіряє собі
    `authorize_resource`."""

    def __init__(self, forged: object, **kwargs: object) -> None:
        super().__init__(PolicyEngine(), **kwargs)  # type: ignore[arg-type]
        self._forged = forged

    def authorize(self, identity: object, spec: object) -> object:  # type: ignore[override]
        del identity, spec
        return self._forged


def test_authorize_resource_does_not_trust_its_own_action_decision_object() -> None:
    """Статичний тип каже «CapabilityPolicyDecision»; рантайм цього не доводить."""
    bridge = _ForgingBridge(
        {"allowed": True},
        action_permissions={ACTION: PERMISSION},
        resource_authorizers={"reference_resource_v1": lambda i, s, r: True},
    )

    with pytest.raises(CapabilityPolicyIndeterminate, match="action decision is invalid"):
        bridge.authorize_resource(_identity(), _spec(), logical_resource="reference:1")
