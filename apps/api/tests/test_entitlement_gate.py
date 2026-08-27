"""Money narrows. The test that matters is the one where it tries to widen.

ACT-001 Workstream D. Four properties:

  * an inactive subscription denies the paid corpus;
  * a *paid* subscription cannot grant a corpus the identity does not hold — the
    intersection, asserted directly, because the union is what gets written by accident;
  * a disabled account entitles nothing regardless of what it paid for;
  * with the gate off, the answer is exactly the policy engine's, unchanged.

The third and fourth are the ones that make this safe to ship: a deployment that has never
sold anything must behave as it did in v6.0.0, and that has to be demonstrated rather than
asserted in a comment.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from korpus.application.paid_access import EntitlementDenied
from korpus.application.policy import UnauthorizedCorporaError
from korpus.domain.tenancy import SubscriptionStatus

from apps.api.tests.tenancy_fixtures import build_tenancy, reader


def _activate(tenancy: Any, subscription_id: Any, *, days: int = 30) -> None:
    moment = datetime.now(UTC)
    body = {
        "id": f"evt-{subscription_id}",
        "type": "subscription.activated",
        "occurred_at": moment.isoformat(),
        "data": {
            "reference": str(subscription_id),
            "period_start": moment.isoformat(),
            "period_end": (moment + timedelta(days=days)).isoformat(),
        },
    }
    payload = json.dumps(body).encode("utf-8")
    tenancy.subscription_service.handle_event(payload, tenancy.provider.sign(payload))


def test_without_an_active_subscription_the_paid_corpus_is_denied(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        identity = reader("oidc|unpaid", frozenset({"public", "training"}))
        account = tenancy.account_service.require_active_account(identity)
        tenancy.plan("standard", frozenset({"training"}))
        tenancy.subscription_service.start_subscription(identity.subject, account.id, "standard")

        gate = tenancy.entitlements(required=True)
        with pytest.raises(EntitlementDenied):
            gate.authorize_corpora(identity, account, ["training"])
    finally:
        tenancy.close()


def test_an_active_subscription_permits_only_what_it_pays_for(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        identity = reader("oidc|paid", frozenset({"public", "training"}))
        account = tenancy.account_service.require_active_account(identity)
        tenancy.plan("standard", frozenset({"training"}))
        subscription = tenancy.subscription_service.start_subscription(
            identity.subject, account.id, "standard"
        )
        _activate(tenancy, subscription.id)

        gate = tenancy.entitlements(required=True)
        assert gate.authorize_corpora(identity, account, ["training"]) == frozenset({"training"})

        # The identity holds `public`; the plan does not pay for it. Narrower, not wider.
        assert gate.authorize_corpora(identity, account, []) == frozenset({"training"})
        with pytest.raises(EntitlementDenied):
            gate.authorize_corpora(identity, account, ["public"])
    finally:
        tenancy.close()


def test_a_plan_cannot_grant_a_corpus_the_identity_does_not_hold(tmp_path: Path) -> None:
    """The one that would let money buy clearance. Intersection, never union."""
    tenancy = build_tenancy(tmp_path)
    try:
        identity = reader("oidc|ambitious", frozenset({"public"}))
        account = tenancy.account_service.require_active_account(identity)
        tenancy.plan("everything", frozenset({"public", "restricted-demo", "training"}))
        subscription = tenancy.subscription_service.start_subscription(
            identity.subject, account.id, "everything"
        )
        _activate(tenancy, subscription.id)

        gate = tenancy.entitlements(required=True)
        # Asking for it by name is refused by the policy engine, which runs first.
        with pytest.raises(UnauthorizedCorporaError):
            gate.authorize_corpora(identity, account, ["restricted-demo"])
        # And asking for everything the plan covers still yields only what is held.
        assert gate.authorize_corpora(identity, account, []) == frozenset({"public"})
    finally:
        tenancy.close()


def test_a_disabled_account_entitles_nothing_however_much_it_paid(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        identity = reader("oidc|paid-then-disabled", frozenset({"training"}))
        account = tenancy.account_service.require_active_account(identity)
        tenancy.plan("standard", frozenset({"training"}))
        subscription = tenancy.subscription_service.start_subscription(
            identity.subject, account.id, "standard"
        )
        _activate(tenancy, subscription.id)

        gate = tenancy.entitlements(required=True)
        assert gate.project(account).grants_paid_access

        disabled = tenancy.account_service.disable(reader("operator"), account.id, reason="revoked")
        projection = gate.project(disabled)
        assert projection.entitled_corpora == frozenset()
        assert projection.reason == "account_disabled"
        with pytest.raises(EntitlementDenied):
            gate.authorize_corpora(identity, disabled, ["training"])
    finally:
        tenancy.close()


def test_an_expired_period_stops_paying_without_any_event_arriving(tmp_path: Path) -> None:
    """A provider that stops sending events leaves a row saying ACTIVE forever."""
    tenancy = build_tenancy(tmp_path)
    try:
        identity = reader("oidc|lapsed", frozenset({"training"}))
        account = tenancy.account_service.require_active_account(identity)
        tenancy.plan("standard", frozenset({"training"}))
        subscription = tenancy.subscription_service.start_subscription(
            identity.subject, account.id, "standard"
        )
        _activate(tenancy, subscription.id, days=1)

        gate = tenancy.entitlements(required=True)
        later = datetime.now(UTC) + timedelta(days=2)
        stored = tenancy.subscriptions.get_subscription(subscription.id)
        assert stored is not None and stored.status is SubscriptionStatus.ACTIVE

        assert gate.project(account, now=later).entitled_corpora == frozenset()
        with pytest.raises(EntitlementDenied):
            gate.authorize_corpora(identity, account, ["training"], now=later)
    finally:
        tenancy.close()


def test_a_free_corpus_needs_no_subscription(tmp_path: Path) -> None:
    tenancy = build_tenancy(tmp_path)
    try:
        identity = reader("oidc|free", frozenset({"public", "training"}))
        account = tenancy.account_service.require_active_account(identity)
        gate = tenancy.entitlements(required=True, free=frozenset({"public"}))

        assert gate.authorize_corpora(identity, account, ["public"]) == frozenset({"public"})
        with pytest.raises(EntitlementDenied):
            gate.authorize_corpora(identity, account, ["training"])
    finally:
        tenancy.close()


def test_with_the_gate_off_the_answer_is_the_policy_engines_own(tmp_path: Path) -> None:
    """The shipped default. A deployment that sells nothing behaves as it did before.

    `resolve_corpora` still runs — the refusal for a corpus the identity does not hold is
    a security decision and must not depend on a commercial switch.
    """
    tenancy = build_tenancy(tmp_path)
    try:
        identity = reader("oidc|nobilling", frozenset({"public", "training"}))
        account = tenancy.account_service.require_active_account(identity)
        gate = tenancy.entitlements(required=False)

        assert gate.enforced is False
        assert gate.authorize_corpora(identity, account, []) == frozenset({"public", "training"})
        assert gate.authorize_corpora(identity, account, ["training"]) == frozenset({"training"})
        with pytest.raises(UnauthorizedCorporaError):
            gate.authorize_corpora(identity, account, ["restricted-demo"])
    finally:
        tenancy.close()


def test_the_schema_refuses_a_subscription_without_a_plan(tmp_path: Path) -> None:
    """The orphan state is unreachable, and that is a stronger statement than a guard.

    A foreign key with no ON DELETE is RESTRICT: a plan that a subscription references
    cannot be deleted, and a subscription cannot be created against a plan that does not
    exist. Asserted here because `EntitlementProjection` also guards against the state,
    and a guard nobody can trigger is a guard nobody can trust — this says which of the
    two is doing the work.
    """
    from uuid import uuid4

    from korpus.domain.tenancy import SubscriptionRecord
    from sqlalchemy.exc import IntegrityError

    tenancy = build_tenancy(tmp_path)
    try:
        identity = reader("oidc|orphan", frozenset({"training"}))
        account = tenancy.account_service.require_active_account(identity)
        with pytest.raises(IntegrityError):
            tenancy.subscriptions.create_subscription(
                identity.subject,
                SubscriptionRecord(
                    account_id=account.id,
                    plan_id=uuid4(),
                    provider="deterministic",
                    status=SubscriptionStatus.ACTIVE,
                ),
            )

        plan = tenancy.plan("standard", frozenset({"training"}))
        tenancy.subscription_service.start_subscription(identity.subject, account.id, "standard")
        from korpus.infrastructure.tenancy_schema import plans
        from sqlalchemy import delete

        with pytest.raises(IntegrityError), tenancy.repository.engine.begin() as connection:
            connection.execute(delete(plans).where(plans.c.id == str(plan.id)))
    finally:
        tenancy.close()


def test_a_subscription_whose_plan_vanished_entitles_nothing() -> None:
    """The guard itself, exercised through a store that can produce the state.

    Falling back to a default when the plan is missing would make a deleted row a way to
    widen access. The database prevents the state; this says what the projection does if
    it ever arrives by another route — a restored backup, a future ON DELETE SET NULL.
    """
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from korpus.application.paid_access import EntitlementProjection
    from korpus.application.policy import PolicyEngine
    from korpus.domain.tenancy import AccountRecord, SubscriptionRecord

    account = AccountRecord(auth_subject="oidc|ghost-plan")
    subscription = SubscriptionRecord(
        account_id=account.id,
        plan_id=uuid4(),
        provider="deterministic",
        status=SubscriptionStatus.ACTIVE,
        current_period_end=datetime.now(UTC) + timedelta(days=30),
    )

    class PlanlessStore:
        def list_subscriptions(self, account_id: Any) -> list[SubscriptionRecord]:
            return [subscription]

        def get_plan(self, plan_id: Any) -> None:
            return None

    projection = EntitlementProjection(
        PlanlessStore(),  # type: ignore[arg-type]
        PolicyEngine(),
        subscription_required=True,
    )
    entitlement = projection.project(account)
    assert entitlement.entitled_corpora == frozenset()
    assert entitlement.reason.startswith("no_active_subscription")


def test_a_past_due_subscription_pays_for_nothing(tmp_path: Path) -> None:
    """No implicit grace period. The mutation gate found this gap: every earlier test
    reached the refusal through INCOMPLETE, so a rule that also honoured PAST_DUE would
    have passed all of them.

    A grace period is a commercial decision somebody makes on purpose. Defaulting to one
    means the first unpaid invoice silently keeps access open, which is the state nobody
    notices until the month it matters.
    """
    tenancy = build_tenancy(tmp_path)
    try:
        identity = reader("oidc|lapsing", frozenset({"training"}))
        account = tenancy.account_service.require_active_account(identity)
        tenancy.plan("standard", frozenset({"training"}))
        subscription = tenancy.subscription_service.start_subscription(
            identity.subject, account.id, "standard"
        )
        _activate(tenancy, subscription.id)

        gate = tenancy.entitlements(required=True)
        assert gate.authorize_corpora(identity, account, ["training"]) == frozenset({"training"})

        moment = datetime.now(UTC) + timedelta(minutes=5)
        body = {
            "id": "evt-past-due",
            "type": "subscription.payment_failed",
            "occurred_at": moment.isoformat(),
            "data": {"reference": str(subscription.id)},
        }
        payload = json.dumps(body).encode("utf-8")
        tenancy.subscription_service.handle_event(payload, tenancy.provider.sign(payload))

        stored = tenancy.subscriptions.get_subscription(subscription.id)
        assert stored is not None and stored.status is SubscriptionStatus.PAST_DUE
        assert gate.project(account).entitled_corpora == frozenset()
        with pytest.raises(EntitlementDenied):
            gate.authorize_corpora(identity, account, ["training"])
    finally:
        tenancy.close()
