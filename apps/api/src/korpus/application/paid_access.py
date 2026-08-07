"""Money can take corpora away. It can never add one.

The projection is Account → Subscription → Entitlement → PolicyEngine, and the arrow at
the end is the only interesting part of it. `PolicyEngine.resolve_corpora` decides what an
identity may read from clearance, corpus assignment and compartments. This module runs
*after* that and takes the intersection with what has been paid for.

Intersection, never union. Written as one line and worth the paragraph, because the union
is the version that gets written by accident and passes every test somebody thinks to
write: with a union, a plan listing `operational` hands `operational` to anybody who buys
it, and a subscription becomes a way to purchase clearance. With an intersection, the
worst a forged billing event can do is fail to remove something.

The gate is off unless an operator turns it on. A deployment that has never sold anything —
which is every deployment of this system today — must not have its answers filtered by a
subscription table nobody populated. `subscription_required=False` is the shipped default
and `authorize_corpora` returns the policy engine's answer untouched; the difference
between the two paths is asserted by test rather than assumed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from korpus.application.policy import AuthorizationError, PolicyEngine
from korpus.application.tenancy_ports import SubscriptionStore
from korpus.domain.models import Identity
from korpus.domain.tenancy import AccountRecord, AccountStatus, SubscriptionEntitlement


class EntitlementDenied(AuthorizationError):
    """No active subscription covers the corpora this request needs.

    A subclass of `AuthorizationError` so every existing handler already refuses it. It is
    a commercial refusal wearing an authorization refusal's clothes, and that is the right
    way round: the failure mode to avoid is a billing state that is *not* enforced, never
    one that is enforced too strictly.
    """

    reason = "no_active_subscription"

    def __init__(self, detail: str, denied: list[str] | None = None) -> None:
        self.denied = list(denied or [])
        super().__init__(detail)


class EntitlementProjection:
    """What an account has paid for, and what that permits once policy has had its say."""

    def __init__(
        self,
        subscriptions: SubscriptionStore,
        policy: PolicyEngine,
        *,
        subscription_required: bool = False,
        free_corpora: frozenset[str] = frozenset(),
    ) -> None:
        self._subscriptions = subscriptions
        self._policy = policy
        self._subscription_required = subscription_required
        self._free_corpora = free_corpora

    @property
    def enforced(self) -> bool:
        """Whether any of this changes an answer. Reported to clients rather than inferred.

        A client that had to guess from an empty entitlement would read "nothing paid for"
        and "billing switched off" as the same state, and show a paywall in a deployment
        that has never sold anything.
        """
        return self._subscription_required

    def project(
        self, account: AccountRecord, *, now: datetime | None = None
    ) -> SubscriptionEntitlement:
        """The entitlement, derived every time rather than stored.

        A cached entitlement is a decision made at a moment that has passed. A card
        expires, a provider cancels, an operator disables an account — and a stored
        entitlement keeps answering with what was true when it was written.
        """
        moment = now or datetime.now(UTC)
        if account.status is not AccountStatus.ACTIVE:
            return SubscriptionEntitlement(
                account_id=account.id,
                entitled_corpora=frozenset(),
                evaluated_at=moment,
                reason="account_disabled",
            )

        candidates = self._subscriptions.list_subscriptions(account.id)
        for subscription in candidates:
            if not subscription.active_at(moment):
                continue
            plan = self._subscriptions.get_plan(subscription.plan_id)
            if plan is None:
                # A subscription pointing at a plan that no longer exists entitles
                # nothing. The alternative — falling back to some default — would make a
                # deleted row a way to widen access.
                continue
            return SubscriptionEntitlement(
                account_id=account.id,
                entitled_corpora=frozenset(plan.entitled_corpora) | self._free_corpora,
                subscription_status=subscription.status,
                plan_code=plan.code,
                evaluated_at=moment,
                reason="active_subscription",
            )

        latest = candidates[0].status if candidates else None
        return SubscriptionEntitlement(
            account_id=account.id,
            entitled_corpora=frozenset(self._free_corpora),
            subscription_status=latest,
            evaluated_at=moment,
            reason=(
                f"no_active_subscription:{latest.value}" if latest else "no_subscription"
            ),
        )

    def authorize_corpora(
        self,
        identity: Identity,
        account: AccountRecord,
        requested: list[str],
        *,
        now: datetime | None = None,
    ) -> frozenset[str]:
        """The corpora this request may search: policy first, then payment.

        `resolve_corpora` runs unconditionally, including when the subscription gate is
        off, because it is the call that raises `UnauthorizedCorporaError` for a corpus the
        identity does not hold. Skipping it when billing is disabled would make an
        operator's commercial switch change a security answer.
        """
        permitted = self._policy.resolve_corpora(identity, requested)
        if not self._subscription_required:
            return permitted

        entitlement = self.project(account, now=now)
        # The intersection. Not a union, not a fallback, not "if empty then permitted":
        # each of those turns a plan into a grant.
        allowed = permitted & entitlement.entitled_corpora
        if not allowed:
            raise EntitlementDenied(
                f"no active subscription covers this request ({entitlement.reason})",
                sorted(permitted),
            )
        return allowed

    def account_denial(self, account_id: UUID, reason: str) -> dict[str, object]:
        """The audit payload for a denial, so the shape is identical wherever it is raised."""
        return {
            "account_id": str(account_id),
            "reason": reason,
            "interpretation": (
                "A paid entitlement was absent or did not cover the requested corpora. "
                "Entitlement is intersected with what the policy engine already permits, "
                "so this refusal can only ever be narrower than the security decision — a "
                "subscription cannot widen clearance, corpus assignment or compartments."
            ),
        }
