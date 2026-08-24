"""Twelve named ways to attack the account layer, each with its own refusal.

ACT-001 Workstream K. The list is fixed and numbered so a reviewer can check it against
the change rather than against a feeling that the tests look thorough:

   T01  forged billing event            unsigned or mis-signed webhook activating a plan
   T02  replayed billing event          a genuine event delivered again, or from last month
   T03  subscription resurrection       canceled → active without a valid transition
   T04  paid-flag injection             a client asserting entitlement in a request body
   T05  entitlement escalation          a plan naming a corpus the identity does not hold
   T06  BOLA / IDOR                     another account's conversation by id
   T07  account enumeration             telling "not yours" apart from "does not exist"
   T08  disabled-account survival       a session that outlives the account being disabled
   T09  identity-claim authorization    an IdP granting corpora by adding a token claim
   T10  history-as-evidence             a prior answer re-entering the answer path
   T11  egress exfiltration             a question leaving a deployment that forbids it
   T12  webhook resource exhaustion     an unauthenticated endpoint reading an unbounded body

Every test here asserts a refusal *and* the absence of the effect. "It returned 403" is
half a test: the other half is that the state did not move.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar
from uuid import uuid4

import pytest
from korpus.application.accounts import AccountProfile, IdentityClaimLeak
from korpus.application.egress import EgressPosture, ModelEgressPolicy
from korpus.application.paid_access import EntitlementDenied
from korpus.application.policy import UnauthorizedCorporaError
from korpus.application.tenancy_ports import (
    AccountDisabled,
    BillingEventRejected,
    ConversationNotFound,
    InvalidSubscriptionTransition,
)
from korpus.domain.tenancy import BillingEventResult, MessageRole, SubscriptionStatus

from apps.api.tests.tenancy_fixtures import build_tenancy, reader


def _signed(tenancy: Any, event_id: str, event_type: str, reference: str, **extra: Any) -> Any:
    moment = extra.pop("occurred_at", None) or datetime.now(UTC)
    body = {
        "id": event_id,
        "type": event_type,
        "occurred_at": moment.isoformat(),
        "data": {
            "reference": reference,
            "period_start": moment.isoformat(),
            "period_end": (moment + timedelta(days=30)).isoformat(),
            **extra,
        },
    }
    payload = json.dumps(body).encode("utf-8")
    return payload, tenancy.provider.sign(payload)


def _paying(tenancy: Any, subject: str = "oidc|t", corpora: frozenset[str] | None = None) -> Any:
    identity = reader(subject, corpora or frozenset({"training"}))
    account = tenancy.account_service.require_active_account(identity)
    tenancy.plan("standard", frozenset({"training"}))
    subscription = tenancy.subscription_service.start_subscription(
        identity.subject, account.id, "standard"
    )
    return identity, account, subscription


def test_t01_a_forged_billing_event_cannot_activate_a_plan(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        _identity, _account, subscription = _paying(tenancy)
        payload, _real = _signed(tenancy, "t01", "subscription.activated", str(subscription.id))

        for signature in (None, "", "deadbeef", "0" * 64):
            with pytest.raises(BillingEventRejected):
                tenancy.subscription_service.handle_event(payload, signature)

        assert tenancy.subscriptions.get_subscription(subscription.id).status is (
            SubscriptionStatus.INCOMPLETE
        )
    finally:
        tenancy.close()


def test_t02_a_replayed_event_is_a_duplicate_and_an_old_one_is_refused(
    tmp_path: Path,
) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        _identity, _account, subscription = _paying(tenancy)
        payload, signature = _signed(tenancy, "t02", "subscription.activated", str(subscription.id))
        assert tenancy.subscription_service.handle_event(payload, signature) is (
            BillingEventResult.APPLIED
        )
        assert tenancy.subscription_service.handle_event(payload, signature) is (
            BillingEventResult.DUPLICATE
        )

        stale, stale_signature = _signed(
            tenancy,
            "t02-old",
            "subscription.canceled",
            str(subscription.id),
            occurred_at=datetime.now(UTC) - timedelta(days=90),
        )
        assert tenancy.subscription_service.handle_event(stale, stale_signature) is (
            BillingEventResult.REJECTED
        )
        assert tenancy.subscriptions.get_subscription(subscription.id).status is (
            SubscriptionStatus.ACTIVE
        )
    finally:
        tenancy.close()


def test_t03_a_canceled_subscription_cannot_be_resurrected(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        _identity, _account, subscription = _paying(tenancy)
        activate, activate_signature = _signed(
            tenancy, "t03-a", "subscription.activated", str(subscription.id)
        )
        tenancy.subscription_service.handle_event(activate, activate_signature)
        cancel, cancel_signature = _signed(
            tenancy,
            "t03-c",
            "subscription.canceled",
            str(subscription.id),
            occurred_at=datetime.now(UTC) + timedelta(seconds=30),
        )
        tenancy.subscription_service.handle_event(cancel, cancel_signature)

        revive, revive_signature = _signed(
            tenancy,
            "t03-r",
            "subscription.activated",
            str(subscription.id),
            occurred_at=datetime.now(UTC) + timedelta(minutes=1),
        )
        with pytest.raises(InvalidSubscriptionTransition):
            tenancy.subscription_service.handle_event(revive, revive_signature)
        assert tenancy.subscriptions.get_subscription(subscription.id).status is (
            SubscriptionStatus.CANCELED
        )
    finally:
        tenancy.close()


def test_t04_no_request_field_can_assert_that_a_subscription_is_paid() -> None:
    """Structural: there is no `paid`, `subscribed` or `entitled` input anywhere.

    A client-supplied boolean is the classic version of this bug, and the defence is not a
    validator — it is that no such field exists to validate.
    """
    from korpus.api import routes_billing, routes_tenancy
    from korpus.domain.models import QueryRequest

    forbidden = {"paid", "is_paid", "subscription", "subscribed", "entitled", "entitlement"}
    for module in (routes_tenancy, routes_billing):
        for name in dir(module):
            candidate = getattr(module, name)
            fields = getattr(candidate, "model_fields", None)
            if not isinstance(fields, dict):
                continue
            leaked = forbidden & set(fields)
            assert not leaked, f"{module.__name__}.{name} accepts {sorted(leaked)} from a client"
    assert not forbidden & set(QueryRequest.model_fields)


def test_t05_a_plan_cannot_escalate_beyond_the_identity(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        identity = reader("oidc|t05", frozenset({"public"}))
        account = tenancy.account_service.require_active_account(identity)
        tenancy.plan("everything", frozenset({"public", "training", "restricted-demo"}))
        subscription = tenancy.subscription_service.start_subscription(
            identity.subject, account.id, "everything"
        )
        payload, signature = _signed(tenancy, "t05", "subscription.activated", str(subscription.id))
        tenancy.subscription_service.handle_event(payload, signature)

        gate = tenancy.entitlements(required=True)
        assert gate.authorize_corpora(identity, account, []) == frozenset({"public"})
        with pytest.raises(UnauthorizedCorporaError):
            gate.authorize_corpora(identity, account, ["restricted-demo"])
    finally:
        tenancy.close()


def test_t06_another_accounts_conversation_is_unreachable_by_id(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        owner = tenancy.account_service.require_active_account(reader("oidc|t06-owner"))
        intruder = tenancy.account_service.require_active_account(reader("oidc|t06-other"))
        service = tenancy.conversation_service
        conversation = service.create(owner, "секретне")
        service.record_question(owner, conversation.id, "питання власника")

        for call in (
            lambda: service.get(intruder, conversation.id),
            lambda: service.messages(intruder, conversation.id),
            lambda: service.archive(intruder, conversation.id),
            lambda: service.record_question(intruder, conversation.id, "вставка"),
        ):
            with pytest.raises(ConversationNotFound):
                call()

        assert len(service.messages(owner, conversation.id).items) == 1
        assert service.get(owner, conversation.id).archived_at is None
    finally:
        tenancy.close()


def test_t07_a_foreign_id_and_a_nonexistent_id_are_indistinguishable(
    tmp_path: Path,
) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        owner = tenancy.account_service.require_active_account(reader("oidc|t07-owner"))
        intruder = tenancy.account_service.require_active_account(reader("oidc|t07-other"))
        conversation = tenancy.conversation_service.create(owner)

        with pytest.raises(ConversationNotFound) as real:
            tenancy.conversation_service.get(intruder, conversation.id)
        with pytest.raises(ConversationNotFound) as invented:
            tenancy.conversation_service.get(intruder, uuid4())
        assert real.value.reason == invented.value.reason
    finally:
        tenancy.close()


def test_t08_disabling_takes_effect_on_the_next_request_not_the_next_login(
    tmp_path: Path,
) -> None:
    """A valid token outlives the disable. The check is per request, so the token is inert."""
    tenancy = build_tenancy(tmp_path)
    try:
        identity = reader("oidc|t08")
        account = tenancy.account_service.require_active_account(identity)
        tenancy.account_service.disable(reader("operator"), account.id, reason="compromised")

        # The same identity object — the same token, in an API deployment.
        with pytest.raises(AccountDisabled):
            tenancy.account_service.require_active_account(identity)
    finally:
        tenancy.close()


def test_t09_an_identity_provider_cannot_grant_corpora_through_a_claim() -> None:
    for claim in ("corpora", "clearance", "roles", "compartments", "entitlements"):
        with pytest.raises(IdentityClaimLeak):
            AccountProfile.from_claims({"sub": "oidc|t09", claim: ["restricted-demo"]})


def test_t10_a_prior_answer_is_stored_as_an_answer_and_not_as_a_source(
    tmp_path: Path,
) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        owner = tenancy.account_service.require_active_account(reader("oidc|t10"))
        service = tenancy.conversation_service
        conversation = service.create(owner)
        service.record_question(owner, conversation.id, "перше питання")
        service.record_answer(owner, conversation.id, "Перша відповідь.", uuid4())

        stored = service.messages(owner, conversation.id).items
        assert stored[1].role is MessageRole.ASSISTANT
        # And the retrieval port has no method that could be handed a message.
        from korpus.application.ports import Retriever

        signature = Retriever.search.__annotations__
        assert "MessageRecord" not in str(signature)
    finally:
        tenancy.close()


def test_t11_a_restricted_deployment_does_not_send_the_question_anywhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from korpus.application.query_plan import PlannerUnavailable
    from korpus.infrastructure import anthropic_planner
    from korpus.infrastructure.anthropic_planner import AnthropicQueryPlanner

    def explode(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("the question left the deployment")

    monkeypatch.setattr(anthropic_planner.httpx, "post", explode)
    for posture in (EgressPosture.MODEL_DISABLED, EgressPosture.LOCAL_ONLY):
        planner = AnthropicQueryPlanner("key", model="m", egress=ModelEgressPolicy(posture))
        with pytest.raises(PlannerUnavailable):
            planner.variants("координати підрозділу", [])


def test_t12_an_unbounded_webhook_body_is_refused_before_it_is_parsed(
    tmp_path: Path,
) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        oversized = b'{"id":"x","type":"subscription.activated","data":{}}' + b" " * (65 * 1024)
        with pytest.raises(BillingEventRejected, match="size"):
            tenancy.subscription_service.handle_event(oversized, tenancy.provider.sign(oversized))
    finally:
        tenancy.close()


def test_every_named_threat_class_has_a_test() -> None:
    """The list in the docstring is the contract; this is what keeps it honest."""
    import re

    source = Path(__file__).read_text(encoding="utf-8")
    named = set(re.findall(r"^   (T\d\d)\s", source, re.MULTILINE))
    tested = {match.upper() for match in re.findall(r"^def test_(t\d\d)_", source, re.MULTILINE)}
    assert named == tested, f"named but untested: {sorted(named - tested)}"
    assert len(named) == 12, f"the list is {len(named)} classes, not twelve"


def test_a_denial_is_not_a_silent_pass(tmp_path: Path) -> None:
    """Every refusal above raises. None of them returns a narrowed-but-usable result."""
    tenancy = build_tenancy(tmp_path)
    try:
        identity, account, _subscription = _paying(tenancy)
        gate = tenancy.entitlements(required=True)
        with pytest.raises(EntitlementDenied) as denial:
            gate.authorize_corpora(identity, account, ["training"])
        assert denial.value.reason == "no_active_subscription"
        assert denial.value.denied == ["training"]
    finally:
        tenancy.close()


def test_t12a_declared_oversize_is_refused_before_stream_consumption() -> None:
    import asyncio

    from fastapi import HTTPException
    from korpus.api.request_limits import bounded_webhook_body

    class Request:
        headers: ClassVar[dict[str, str]] = {"content-length": str(64 * 1024 + 1)}

        async def stream(self):
            raise AssertionError("oversized declared body was consumed")
            yield b""

    with pytest.raises(HTTPException) as denial:
        asyncio.run(bounded_webhook_body(Request()))  # type: ignore[arg-type]
    assert denial.value.status_code == 413


def test_t12b_chunked_oversize_stops_at_the_first_excess_chunk() -> None:
    import asyncio

    from fastapi import HTTPException
    from korpus.api.request_limits import bounded_webhook_body

    class Request:
        headers: ClassVar[dict[str, str]] = {}

        async def stream(self):
            yield b"a" * (64 * 1024)
            yield b"b"
            raise AssertionError("reader continued after the hard ceiling")

    with pytest.raises(HTTPException) as denial:
        asyncio.run(bounded_webhook_body(Request()))  # type: ignore[arg-type]
    assert denial.value.status_code == 413
