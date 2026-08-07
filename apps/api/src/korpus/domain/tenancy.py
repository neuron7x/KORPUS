"""Account, subscription and conversation — the things a customer has, kept apart.

ACT-001 adds a product around the answer kernel: people log in, pay, and keep a history
of what they asked. Four concepts arrive together and the whole design is that they stay
four:

  identity        who the identity provider says this is. A claim from outside.
  account         who this is *here*. Created on first login, disabled by us, never by
                  the provider.
  entitlement     what has been paid for. Commercial, and reversible by a card expiring.
  authorization   what may be read. Clearance, corpus, compartment — the existing
                  `PolicyEngine`, untouched.

Collapsing any two of them is the failure this module exists against. The one that costs
lives is collapsing the last two: a paid subscription that widens what a soldier may read
would mean money buying clearance. `SubscriptionEntitlement` can only ever *narrow*, and
`policy.py` never learns that billing exists.

The second: a conversation is context, not evidence. Yesterday's answer sitting in a
history is a sentence the system wrote, and treating it as a source would let the system
cite itself into any conclusion in three turns. `Message.role` exists so that boundary is
representable rather than remembered.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AccountStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class SubscriptionStatus(StrEnum):
    """The provider's lifecycle, named here so no provider's vocabulary leaks inward.

    `INCOMPLETE` is a subscription that exists and has never been paid for. It is not
    ACTIVE and is not an error: a checkout that was started and abandoned leaves one, and
    a system that treated it as either would be wrong about a customer who is about to
    pay or about one who never will.
    """

    INCOMPLETE = "incomplete"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    EXPIRED = "expired"

    @property
    def grants_entitlement(self) -> bool:
        """Only ACTIVE pays for anything.

        `PAST_DUE` is deliberately excluded. A grace period is a commercial decision
        somebody has to make on purpose, and defaulting to one means the first unpaid
        invoice silently keeps access open — which is the state nobody notices until the
        month it matters.
        """
        return self is SubscriptionStatus.ACTIVE


class PlanStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"


class BillingInterval(StrEnum):
    MONTHLY = "monthly"
    YEARLY = "yearly"


class MessageRole(StrEnum):
    """Who said it. The distinction the evidence rule rests on.

    An `ASSISTANT` message is a sentence this system emitted. It carries citations and it
    is not itself a source: re-reading it as evidence would let the system cite itself,
    and three turns of that reaches any conclusion with a full-looking citation list.
    """

    USER = "user"
    ASSISTANT = "assistant"


class BillingEventResult(StrEnum):
    APPLIED = "applied"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


#: Transitions a provider event may cause. Anything absent is rejected rather than
#: applied: a webhook that claims `canceled → active` is either a replay, a forgery, or a
#: provider bug, and all three are reasons to stop rather than to widen access.
ALLOWED_SUBSCRIPTION_TRANSITIONS: dict[SubscriptionStatus, frozenset[SubscriptionStatus]] = {
    SubscriptionStatus.INCOMPLETE: frozenset(
        {SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELED, SubscriptionStatus.EXPIRED}
    ),
    SubscriptionStatus.ACTIVE: frozenset(
        {
            SubscriptionStatus.PAST_DUE,
            SubscriptionStatus.CANCELED,
            SubscriptionStatus.EXPIRED,
            SubscriptionStatus.ACTIVE,
        }
    ),
    SubscriptionStatus.PAST_DUE: frozenset(
        {SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELED, SubscriptionStatus.EXPIRED}
    ),
    # Terminal. A renewal after cancellation is a *new* subscription with its own
    # provider id, not the old row waking up — otherwise a single replayed event
    # resurrects access nobody paid for.
    SubscriptionStatus.CANCELED: frozenset(),
    SubscriptionStatus.EXPIRED: frozenset(),
}


def _now() -> datetime:
    return datetime.now(UTC)


class AccountRecord(BaseModel):
    """The application's own idea of a customer.

    `auth_subject` is the identity provider's opaque subject and is unique here. Email is
    optional and deliberately not the key: providers change it, people share it, and an
    account keyed on it merges two customers the day one of them updates their address.
    """

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    auth_subject: str = Field(min_length=1, max_length=255)
    email: str | None = Field(default=None, max_length=320)
    display_name: str | None = Field(default=None, max_length=200)
    status: AccountStatus = AccountStatus.ACTIVE
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    disabled_at: datetime | None = None

    @field_validator("auth_subject")
    @classmethod
    def _no_control_characters(cls, value: str) -> str:
        if any(character.isspace() and character != " " for character in value):
            raise ValueError("auth_subject carries control characters")
        return value

    @property
    def usable(self) -> bool:
        return self.status is AccountStatus.ACTIVE


class PlanRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    name: str = Field(min_length=1, max_length=200)
    status: PlanStatus = PlanStatus.ACTIVE
    billing_interval: BillingInterval = BillingInterval.MONTHLY
    #: What the payment provider calls this. Nullable because a plan exists here before
    #: anybody has been asked to sell it, and inventing a provider reference to fill the
    #: column would be a credential this repository does not have.
    external_product_reference: str | None = Field(default=None, max_length=255)
    external_price_reference: str | None = Field(default=None, max_length=255)
    #: Which corpora this plan pays for. Empty means a plan that grants no paid corpus —
    #: which is a real plan, not a misconfiguration: the free tier is one.
    entitled_corpora: frozenset[str] = Field(default_factory=frozenset)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class SubscriptionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    account_id: UUID
    plan_id: UUID
    provider: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    provider_customer_id: str | None = Field(default=None, max_length=255)
    provider_subscription_id: str | None = Field(default=None, max_length=255)
    status: SubscriptionStatus = SubscriptionStatus.INCOMPLETE
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    def active_at(self, moment: datetime) -> bool:
        """Whether this pays for anything at this instant.

        The period end is checked as well as the status, because a provider that stops
        sending events — a webhook endpoint that broke, an account that was deleted at
        their end — leaves a row that says ACTIVE forever. The clock is the one input
        that arrives without anybody's cooperation.
        """
        if not self.status.grants_entitlement:
            return False
        if self.current_period_end is not None and moment >= self.current_period_end:
            return False
        return not (self.current_period_start is not None and moment < self.current_period_start)


class BillingEventRecord(BaseModel):
    """One notification from a provider, recorded before it is believed.

    `payload_hash` rather than the payload: the body carries customer names, emails and
    card metadata, and an audit trail that keeps them becomes a second place they can
    leak from. The hash answers "was this the same event" without holding it.
    """

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    provider: str = Field(min_length=1, max_length=64)
    provider_event_id: str = Field(min_length=1, max_length=255)
    event_type: str = Field(min_length=1, max_length=128)
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    received_at: datetime = Field(default_factory=_now)
    processed_at: datetime | None = None
    processing_result: BillingEventResult | None = None


class ConversationRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    account_id: UUID
    title: str | None = Field(default=None, max_length=200)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    archived_at: datetime | None = None


class MessageRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID
    role: MessageRole
    raw_text: str = Field(min_length=1, max_length=20_000)
    #: The answer this message *is*, when it is one. A link, not a copy: the answer and
    #: its citations live in the answer path, and duplicating them here would create a
    #: second version of what the system said that nothing keeps in step.
    answer_id: UUID | None = None
    created_at: datetime = Field(default_factory=_now)


class SubscriptionEntitlement(BaseModel):
    """What has been paid for, in a form the authorization layer can consume.

    It carries corpora and nothing else — no clearance, no compartment, no role. That is
    the whole point: `PolicyEngine` decides what may be read, and the only thing money can
    do is fail to appear in this set. A paid subscription never widens clearance, because
    there is no field here through which it could.
    """

    model_config = ConfigDict(frozen=True)

    account_id: UUID
    entitled_corpora: frozenset[str] = Field(default_factory=frozenset)
    subscription_status: SubscriptionStatus | None = None
    plan_code: str | None = None
    evaluated_at: datetime = Field(default_factory=_now)
    reason: str = ""

    @property
    def grants_paid_access(self) -> bool:
        return bool(self.entitled_corpora)
