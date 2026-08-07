"""One place that builds the ACT-001 stores, so six test files do not build them six ways.

Not a `conftest.py` fixture: several of these tests need two stores over the *same*
database inside one test — the race case needs two writers, the entitlement case needs a
plan writer and a reader — and a fixture that yields one object cannot express that.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from korpus.application.accounts import AccountService
from korpus.application.conversations import ConversationService
from korpus.application.paid_access import EntitlementProjection
from korpus.application.policy import PolicyEngine
from korpus.application.subscriptions import SubscriptionService
from korpus.domain.models import AccessTier, Identity
from korpus.domain.tenancy import PlanRecord
from korpus.infrastructure.billing_repository import SqlSubscriptionStore
from korpus.infrastructure.conversation_repository import SqlConversationStore
from korpus.infrastructure.deterministic_billing import DeterministicBillingProvider
from korpus.infrastructure.repository import SqlRepository
from korpus.infrastructure.tenancy_repository import SqlAccountStore

WEBHOOK_SECRET = "a" * 48


def reader(subject: str = "reader-1", corpora: frozenset[str] | None = None) -> Identity:
    return Identity(
        subject=subject,
        roles=frozenset({"user"}),
        clearance=AccessTier.AUTHENTICATED,
        corpora=corpora if corpora is not None else frozenset({"public", "training"}),
    )


@dataclass
class Tenancy:
    repository: SqlRepository
    accounts: SqlAccountStore
    subscriptions: SqlSubscriptionStore
    conversations: SqlConversationStore
    account_service: AccountService
    conversation_service: ConversationService
    subscription_service: SubscriptionService
    provider: DeterministicBillingProvider
    policy: PolicyEngine

    def entitlements(
        self, *, required: bool = True, free: frozenset[str] = frozenset()
    ) -> EntitlementProjection:
        return EntitlementProjection(
            self.subscriptions,
            self.policy,
            subscription_required=required,
            free_corpora=free,
        )

    def plan(self, code: str, corpora: frozenset[str]) -> PlanRecord:
        return self.subscriptions.upsert_plan(
            PlanRecord(code=code, name=code.title(), entitled_corpora=corpora)
        )

    def close(self) -> None:
        self.repository.close()


def build_tenancy(tmp_path: Path, name: str = "tenancy") -> Tenancy:
    policy = PolicyEngine()
    repository = SqlRepository(
        f"sqlite:///{tmp_path / f'{name}.db'}",
        f"{name}-audit-key",
        policy,
        tmp_path / f"{name}-anchor.json",
    )
    repository.initialize()
    accounts = SqlAccountStore(repository)
    subscriptions = SqlSubscriptionStore(repository)
    conversations = SqlConversationStore(repository)
    provider = DeterministicBillingProvider(WEBHOOK_SECRET)
    return Tenancy(
        repository=repository,
        accounts=accounts,
        subscriptions=subscriptions,
        conversations=conversations,
        account_service=AccountService(accounts),
        conversation_service=ConversationService(conversations),
        subscription_service=SubscriptionService(subscriptions, accounts, provider),
        provider=provider,
        policy=policy,
    )
