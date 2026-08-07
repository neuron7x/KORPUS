"""What the account, billing and conversation services need from storage.

Separate from `ports.py` for the reason that file exists at all: the answer kernel's ports
are about evidence, and these are about customers. A service that can reach the corpus
repository can reach `list_retrievable_spans`, and the billing path has no business being
one import away from it.

The exceptions are here rather than in the adapters because they are part of the contract.
`AccountDisabled` in particular is raised in one place and caught in the API layer, and a
service that returned `None` instead would leave every caller to decide what a disabled
account means — which is how one of them decides it means "carry on".
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from korpus.domain.tenancy import (
    AccountRecord,
    AccountStatus,
    BillingEventRecord,
    BillingEventResult,
    ConversationRecord,
    MessageRecord,
    MessageRole,
    PlanRecord,
    SubscriptionRecord,
    SubscriptionStatus,
)


class TenancyError(RuntimeError):
    """Base for every refusal in this domain, so nothing here is caught by accident."""


class AccountDisabled(TenancyError):
    """The subject authenticated and the account they map to is switched off.

    Distinct from "not authenticated" on purpose: an operator disabling an account needs
    to see that the block held, and a 401 would send the person back through a login that
    will succeed and change nothing.
    """

    reason = "account_disabled"


class AccountNotFound(TenancyError):
    reason = "account_not_found"


class ConversationNotFound(TenancyError):
    """Also raised when the conversation exists and belongs to somebody else.

    Deliberately one exception. Distinguishing them tells an unauthorized caller that the
    identifier they guessed is real, which is half of what enumeration needs.
    """

    reason = "conversation_not_found"


class ConversationArchived(TenancyError):
    reason = "conversation_archived"


class SubscriptionNotFound(TenancyError):
    reason = "subscription_not_found"


class PlanNotFound(TenancyError):
    reason = "plan_not_found"


class InvalidSubscriptionTransition(TenancyError):
    """A provider event asked for a transition the lifecycle does not permit.

    Carries both states because the useful question afterwards is not "did it fail" but
    "what did the provider think the subscription was", and that is usually the beginning
    of a reconciliation rather than a bug here.
    """

    reason = "invalid_subscription_transition"

    def __init__(self, current: SubscriptionStatus, requested: SubscriptionStatus) -> None:
        self.current = current
        self.requested = requested
        super().__init__(f"cannot move subscription from {current} to {requested}")


class BillingEventRejected(TenancyError):
    """The event was recorded and not applied. The detail is the reason it was not."""

    reason = "billing_event_rejected"

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class AccountStore(Protocol):
    def ensure_account(
        self,
        auth_subject: str,
        *,
        email: str | None = None,
        display_name: str | None = None,
    ) -> tuple[AccountRecord, bool]:
        """The account for this subject, creating it once if it is new.

        Returns `(account, created)`. Idempotent under concurrency by the unique
        constraint on `auth_subject`, not by a read-then-write: two first logins landing
        together is the normal case for a client that opens two tabs.
        """
        ...

    def get_account(self, account_id: UUID) -> AccountRecord | None: ...

    def get_account_by_subject(self, auth_subject: str) -> AccountRecord | None: ...

    def set_account_status(
        self,
        actor_subject: str,
        account_id: UUID,
        status: AccountStatus,
        *,
        reason: str,
    ) -> AccountRecord: ...


class SubscriptionStore(Protocol):
    def upsert_plan(self, plan: PlanRecord) -> PlanRecord: ...

    def list_plans(self, *, include_retired: bool = False) -> list[PlanRecord]: ...

    def get_plan(self, plan_id: UUID) -> PlanRecord | None: ...

    def get_plan_by_code(self, code: str) -> PlanRecord | None: ...

    def create_subscription(
        self, actor_subject: str, subscription: SubscriptionRecord
    ) -> SubscriptionRecord: ...

    def get_subscription(self, subscription_id: UUID) -> SubscriptionRecord | None: ...

    def list_subscriptions(self, account_id: UUID) -> list[SubscriptionRecord]: ...

    def find_subscription_by_provider_id(
        self, provider: str, provider_subscription_id: str
    ) -> SubscriptionRecord | None: ...

    def record_billing_event(
        self,
        event: BillingEventRecord,
        *,
        subscription_id: UUID | None,
        result: BillingEventResult,
        applied_status: SubscriptionStatus | None,
        period_start: datetime | None,
        period_end: datetime | None,
        cancel_at_period_end: bool | None,
        provider_subscription_id: str | None = None,
        audit_payload: dict[str, Any],
    ) -> BillingEventResult:
        """Record the event and, if it applies, move the subscription — in one commit.

        One method rather than two because the two halves are the invariant: an event
        stored without its effect leaves a subscription that never changed and an
        idempotency key that says it did, and the redelivery that would have fixed it is
        now a duplicate.
        """
        ...

    def get_billing_event(
        self, provider: str, provider_event_id: str
    ) -> BillingEventRecord | None: ...


class ConversationStore(Protocol):
    def create_conversation(self, conversation: ConversationRecord) -> ConversationRecord: ...

    def list_conversations(
        self,
        account_id: UUID,
        *,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ConversationRecord], bool]:
        """One page, and whether another exists. See the adapter for why not a count."""
        ...

    def get_conversation(
        self, account_id: UUID, conversation_id: UUID
    ) -> ConversationRecord | None:
        """Scoped by owner in the query, not filtered afterwards.

        A store method that returned any conversation and left ownership to the caller is
        one forgotten check away from the whole class of broken-object-level-authorization
        bugs. The account id is a parameter so it cannot be forgotten.
        """
        ...

    def archive_conversation(
        self, account_id: UUID, conversation_id: UUID
    ) -> ConversationRecord: ...

    def append_message(self, account_id: UUID, message: MessageRecord) -> MessageRecord: ...

    def list_messages(
        self,
        account_id: UUID,
        conversation_id: UUID,
        *,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[MessageRecord], bool]: ...


class BillingProvider(Protocol):
    """The payment processor, as this system uses it.

    Narrow on purpose. Everything below is about *verifying* what arrived and naming what
    it means; nothing here charges a card, and no method returns a status this system then
    trusts without checking the transition against the lifecycle.
    """

    name: str

    def verify_event(self, payload: bytes, signature: str | None) -> dict[str, Any]:
        """Parse and authenticate a webhook body, or raise.

        `payload` is the raw bytes as received, because a signature covers the bytes and
        re-serialising parsed JSON changes them. Every provider gets this wrong at least
        once by hashing `json.dumps(json.loads(body))`.
        """
        ...

    def event_identity(self, event: dict[str, Any]) -> tuple[str, str]:
        """`(provider_event_id, event_type)`."""
        ...

    def subscription_view(self, event: dict[str, Any]) -> dict[str, Any]:
        """What this event says the subscription now is, in this system's vocabulary."""
        ...


class MessageAppender(Protocol):
    """Narrow write seam for the answer path: it appends, it does not read history."""

    def append_message(
        self,
        account_id: UUID,
        conversation_id: UUID,
        role: MessageRole,
        raw_text: str,
        answer_id: UUID | None = None,
    ) -> MessageRecord: ...
