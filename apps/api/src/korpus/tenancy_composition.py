"""Wiring for the account, billing and conversation services.

A second composition root beside `composition.py`, for the same reason that one exists: the
application layer states what it needs as protocols in `application/tenancy_ports.py`, the
infrastructure layer provides SQL adapters, and something has to name both. It is separate
from `composition.py` because that module wires the ingestion path, and one module wiring
two unrelated subsystems is how a composition root becomes the place everything is
imported from.

The one decision taken here rather than passed through is which billing provider exists.
There is no vendor account for this system, so `DeterministicBillingProvider` is the only
implementation — real in every respect the rest of the code can observe (it authenticates
a webhook with an HMAC over the raw bytes and refuses everything malformed), and it
charges nobody. `SUP-BILLING-001` records the external work.
"""

from __future__ import annotations

from typing import Any

from korpus.application.accounts import AccountService
from korpus.application.conversations import ConversationService
from korpus.application.egress import EgressPosture, ModelEgressPolicy
from korpus.application.paid_access import EntitlementProjection
from korpus.application.policy import PolicyEngine
from korpus.application.subscriptions import SubscriptionService
from korpus.config import Settings
from korpus.domain.models import AccessTier
from korpus.infrastructure.billing_repository import SqlSubscriptionStore
from korpus.infrastructure.conversation_repository import SqlConversationStore
from korpus.infrastructure.deterministic_billing import DeterministicBillingProvider
from korpus.infrastructure.repository import SqlRepository
from korpus.infrastructure.tenancy_repository import SqlAccountStore


def build_egress_policy(settings: Settings) -> ModelEgressPolicy:
    return ModelEgressPolicy(
        EgressPosture(settings.model_egress_posture),
        max_external_tier=AccessTier.parse(settings.model_egress_max_tier),
    )


def install_tenancy(
    state: Any, settings: Settings, repository: SqlRepository, policy: PolicyEngine
) -> None:
    """Attach every ACT-001 service to the application state.

    The loop lives here rather than in `create_app` for a reason the module-budget gate
    made concrete: `create_app` is already at its complexity ceiling, and a start-up
    function that keeps absorbing one more branch per feature is how it got there. The
    wiring is this module's job anyway.
    """
    for name, service in build_tenancy(settings, repository, policy).items():
        setattr(state, name, service)


def build_tenancy(
    settings: Settings, repository: SqlRepository, policy: PolicyEngine
) -> dict[str, Any]:
    """Every ACT-001 service, keyed by the `app.state` attribute it becomes.

    A dict rather than eight positional returns: the caller sets them onto `app.state` in
    a loop, and a tuple with eight elements is one reordering away from a subscription
    service answering account questions.
    """
    account_store = SqlAccountStore(repository)
    subscription_store = SqlSubscriptionStore(repository)
    conversation_store = SqlConversationStore(repository)

    secret = settings.resolved_billing_webhook_secret
    # No secret means no webhook endpoint. An endpoint that accepts unsigned billing
    # events is worse than no endpoint: it is a way for anybody who can reach the port to
    # activate a subscription.
    provider = DeterministicBillingProvider(secret) if secret else None

    return {
        "account_service": AccountService(account_store),
        "account_store": account_store,
        "subscription_store": subscription_store,
        "conversation_service": ConversationService(conversation_store),
        "conversation_store": conversation_store,
        "billing_provider": provider,
        "subscription_service": (
            SubscriptionService(subscription_store, account_store, provider)
            if provider is not None
            else None
        ),
        "entitlements": EntitlementProjection(
            subscription_store,
            policy,
            subscription_required=settings.subscription_required,
            free_corpora=settings.free_corpus_set,
        ),
        "egress_policy": build_egress_policy(settings),
    }
