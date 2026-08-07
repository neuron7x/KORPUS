"""No request left this process. Asserted by making one impossible to miss.

ACT-001 Workstream G. The check that matters is not "the policy returned False" — it is
that no HTTP call was attempted. So the transport is replaced with a function that fails
the test if it is ever reached, and then the planner and the composer are asked to do
their jobs.

`LOCAL_ONLY` is checked against resolved addresses rather than against a hostname, because
`internal.example.com` pointing at a public IP is the shape of the mistake nobody catches
by reading the configuration file.
"""

from __future__ import annotations

from typing import Any, NoReturn

import pytest
from korpus.application.egress import EgressDenied, EgressPosture, ModelEgressPolicy, guarded
from korpus.application.query_plan import PlannerUnavailable
from korpus.infrastructure import anthropic_planner
from korpus.infrastructure.anthropic_planner import AnthropicAnswerComposer, AnthropicQueryPlanner


@pytest.fixture
def no_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args: Any, **kwargs: Any) -> NoReturn:
        raise AssertionError("an outbound request was attempted under a restrictive posture")

    monkeypatch.setattr(anthropic_planner.httpx, "post", explode)


def test_a_disabled_posture_stops_the_planner_before_it_calls_out(
    no_transport: None,
) -> None:
    planner = AnthropicQueryPlanner(
        "key", model="m", egress=ModelEgressPolicy(EgressPosture.MODEL_DISABLED)
    )
    with pytest.raises(PlannerUnavailable) as refusal:
        planner.variants("як накласти турнікет", [])
    assert "egress denied" in str(refusal.value)


def test_a_disabled_posture_stops_the_composer_before_it_calls_out(
    no_transport: None,
) -> None:
    composer = AnthropicAnswerComposer(
        "key", model="m", egress=ModelEgressPolicy(EgressPosture.MODEL_DISABLED)
    )
    with pytest.raises(PlannerUnavailable):
        composer.compose("питання", ["речення"])


def test_local_only_refuses_a_vendor_endpoint(no_transport: None) -> None:
    policy = ModelEgressPolicy(EgressPosture.LOCAL_ONLY)
    planner = AnthropicQueryPlanner(
        "key", model="m", base_url="https://api.anthropic.com", egress=policy
    )
    with pytest.raises(PlannerUnavailable):
        planner.variants("питання", [])


def test_local_only_refuses_an_unconfigured_endpoint() -> None:
    """No endpoint under LOCAL_ONLY means the vendor default, which is the internet."""
    policy = ModelEgressPolicy(EgressPosture.LOCAL_ONLY)
    with pytest.raises(EgressDenied):
        policy.check("")
    with pytest.raises(EgressDenied):
        policy.check(None)


def test_local_only_permits_a_loopback_endpoint() -> None:
    policy = ModelEgressPolicy(EgressPosture.LOCAL_ONLY)
    policy.check("http://127.0.0.1:8080")
    policy.check("http://localhost:11434/v1")
    assert guarded(policy, "http://127.0.0.1:8080") is True


def test_local_only_refuses_a_host_that_cannot_be_resolved() -> None:
    """Unresolvable is not local: a host nobody can resolve cannot be shown to be inside."""
    policy = ModelEgressPolicy(EgressPosture.LOCAL_ONLY)
    with pytest.raises(EgressDenied):
        policy.check("https://this-name-does-not-resolve.invalid/v1")


def test_local_only_refuses_a_name_that_resolves_to_a_public_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The configuration-file mistake: an internal-looking name pointing outside."""
    import socket

    def resolve(host: str, *args: Any, **kwargs: Any) -> list[Any]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    policy = ModelEgressPolicy(EgressPosture.LOCAL_ONLY)
    with pytest.raises(EgressDenied):
        policy.check("https://internal.example.com/v1")


def test_a_name_resolving_to_both_private_and_public_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every address, not any: the next lookup may return the public one."""
    import socket

    def resolve(host: str, *args: Any, **kwargs: Any) -> list[Any]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    policy = ModelEgressPolicy(EgressPosture.LOCAL_ONLY)
    with pytest.raises(EgressDenied):
        policy.check("https://split-horizon.example.com/v1")


def test_a_non_http_scheme_is_refused() -> None:
    policy = ModelEgressPolicy(EgressPosture.LOCAL_ONLY)
    for target in ("file:///etc/passwd", "gopher://127.0.0.1", "127.0.0.1:8080"):
        with pytest.raises(EgressDenied):
            policy.check(target)


def test_the_permissive_posture_is_the_shipped_default() -> None:
    """Every earlier release called out when configured to. Nothing regresses silently."""
    policy = ModelEgressPolicy()
    assert policy.posture is EgressPosture.EXTERNAL_ALLOWED
    assert policy.models_permitted is True
    policy.check("https://api.anthropic.com")


def test_the_settings_value_maps_onto_the_posture() -> None:
    from korpus.config import Settings
    from korpus.tenancy_composition import build_egress_policy

    for value, expected in (
        ("external_allowed", EgressPosture.EXTERNAL_ALLOWED),
        ("local_only", EgressPosture.LOCAL_ONLY),
        ("model_disabled", EgressPosture.MODEL_DISABLED),
    ):
        settings = Settings(
            environment="test",
            auth_mode="dev",
            dev_mode_acknowledgement="I_ACKNOWLEDGE_DEV_AUTH_IS_INSECURE",
            bind_host="127.0.0.1",
            model_egress_posture=value,
        )
        assert build_egress_policy(settings).posture is expected

    with pytest.raises(ValueError):
        Settings(
            environment="test",
            auth_mode="dev",
            dev_mode_acknowledgement="I_ACKNOWLEDGE_DEV_AUTH_IS_INSECURE",
            bind_host="127.0.0.1",
            model_egress_posture="whatever",
        )


def test_model_disabled_refuses_even_a_local_endpoint(no_transport: None) -> None:
    """The mutation gate found this gap: MODEL_DISABLED was only ever tested against a
    vendor URL, which `LOCAL_ONLY` would also refuse. A posture that means "no model" has
    to refuse the model running on this very machine.
    """
    policy = ModelEgressPolicy(EgressPosture.MODEL_DISABLED)
    for target in ("http://127.0.0.1:11434", "http://localhost:8080/v1", "", None):
        with pytest.raises(EgressDenied):
            policy.check(target)
    assert policy.models_permitted is False

    planner = AnthropicQueryPlanner(
        "key", model="m", base_url="http://127.0.0.1:11434", egress=policy
    )
    with pytest.raises(PlannerUnavailable):
        planner.variants("питання", [])
