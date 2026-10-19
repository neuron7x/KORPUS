from dataclasses import replace

import pytest
from korpus.application.capability_gateway.audit import InvocationOutcome
from korpus.application.capability_gateway.effects import EffectState
from korpus.application.capability_gateway.types import EffectClass

from apps.api.tests.test_capability_gateway_invoke import _gateway, _identity, _request, _spec


@pytest.mark.parametrize(
    "change",
    [
        None,
        False,
        {},
        {"allowed": False},
        {"allowed": 1},
        {"capability_id": "other"},
        {"capability_version": "9.0.0"},
        {"action": "other"},
        {"canonical_permission": "other"},
    ],
)
def test_resource_decision_is_attested_before_dispatch(monkeypatch, change):
    gateway, adapter, ledger, _ = _gateway(spec=_spec(effect=EffectClass.WRITE_REMOTE))
    policy = gateway._policy
    valid = policy.authorize_resource(_identity(), _spec(), logical_resource="reference:1")
    decision = replace(valid, **change) if isinstance(change, dict) and change else change
    monkeypatch.setattr(policy, "authorize_resource", lambda *a, **kw: decision)
    result = gateway.invoke(identity=_identity(), request=_request(idempotency_key="one"))
    assert (result.outcome, result.error_code) == (InvocationOutcome.FAILED, "POLICY_UNKNOWN")
    assert adapter.calls == 0
    assert ledger.records == {}
    assert result.output is None


@pytest.mark.parametrize("stage", ["input", "output"])
@pytest.mark.parametrize("sentinel", [False, True, 0, 1, "allowed", {}, []])
def test_injected_schema_requires_none(monkeypatch, stage, sentinel):
    gateway, adapter, ledger, _ = _gateway(spec=_spec(effect=EffectClass.WRITE_REMOTE))
    monkeypatch.setattr(
        gateway._executor._schemas,
        "validate",
        lambda schema_id, value: sentinel if f":{stage}:" in schema_id else None,
    )
    request = _request(idempotency_key="one")
    result = gateway.invoke(identity=_identity(), request=request)
    assert (result.outcome, result.error_code) == (InvocationOutcome.FAILED, "INTERNAL_ERROR")
    assert result.output is None
    assert result.evidence is None
    assert adapter.calls == (stage == "output")
    if stage == "input":
        assert ledger.records == {}
    else:
        assert ledger.records[("reader", "one")].state is EffectState.COMMITTED
        replay = gateway.invoke(identity=_identity(), request=request)
        assert replay.error_code == "IDEMPOTENT_REPLAY_COMMITTED"
        assert adapter.calls == 1


def test_bound_allow_and_none_validators_permit_success():
    gateway, adapter, _, audit = _gateway()
    result = gateway.invoke(identity=_identity(), request=_request())
    assert result.outcome is InvocationOutcome.SUCCESS
    assert result.output == {"value": "ok"}
    assert adapter.calls == len(audit.calls) == 1
