"""Composition root for account, conversation, entitlement and model-egress services."""

from __future__ import annotations

from typing import Any

from korpus.application.accounts import AccountService
from korpus.application.conversations import ConversationService
from korpus.application.egress import EgressPosture, ModelEgressPolicy
from korpus.application.paid_access import EntitlementProjection
from korpus.application.policy import PolicyEngine
from korpus.billing_composition import build_billing
from korpus.config import Settings
from korpus.domain.models import AccessTier
from korpus.infrastructure.billing_repository import SqlSubscriptionStore
from korpus.infrastructure.conversation_repository import SqlConversationStore
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
    for name, service in build_tenancy(settings, repository, policy).items():
        setattr(state, name, service)


def build_tenancy(
    settings: Settings, repository: SqlRepository, policy: PolicyEngine
) -> dict[str, Any]:
    accounts = SqlAccountStore(repository)
    subscriptions = SqlSubscriptionStore(repository)
    conversations = SqlConversationStore(repository)
    services = {
        "account_service": AccountService(accounts),
        "account_store": accounts,
        "subscription_store": subscriptions,
        "conversation_service": ConversationService(conversations),
        "conversation_store": conversations,
        "entitlements": EntitlementProjection(
            subscriptions,
            policy,
            subscription_required=settings.subscription_required,
            free_corpora=settings.free_corpus_set,
        ),
        "egress_policy": build_egress_policy(settings),
    }
    services.update(build_billing(settings, accounts, subscriptions))
    return services
