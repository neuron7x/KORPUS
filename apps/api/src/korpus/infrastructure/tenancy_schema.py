"""Tables for accounts, subscriptions and conversations, on the corpus metadata.

Same `MetaData` as `schema.py` — one database, one migration graph, one `create_all`, and
`initialize(create_schema=False)` compares the whole set against what alembic actually
built. A second metadata would mean a table that exists in the code and not in the
database, which is exactly the class of failure that check exists to catch.

Three constraints here do the load-bearing work, and each is in the database rather than
in a service because a uniqueness rule enforced by a `SELECT` before an `INSERT` is not a
rule, it is a race:

  ``uq_accounts_auth_subject``    two concurrent first logins for one identity cannot
                                  both create an account.
  ``uq_billing_event_identity``   a provider that redelivers a webhook — which every
                                  provider does — cannot apply it twice.
  ``uq_subscription_provider_id`` one provider subscription maps to at most one row here.

The ownership indexes exist for the same reason as the foreign keys: every read of a
conversation is filtered by `account_id`, and a filter that scans is a filter somebody
eventually removes.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Table,
    Text,
    UniqueConstraint,
)

from korpus.infrastructure.schema import metadata

accounts = Table(
    "accounts",
    metadata,
    Column("id", String(36), primary_key=True),
    # The identity provider's subject. Unique here, and the only column that ties a
    # customer to a login: email is mutable at the provider and shared by people, so an
    # account keyed on it merges two customers the day one of them updates their address.
    Column("auth_subject", String(255), nullable=False),
    Column("email", String(320)),
    Column("display_name", String(200)),
    Column("status", String(32), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("disabled_at", DateTime(timezone=True)),
    UniqueConstraint("auth_subject", name="uq_accounts_auth_subject"),
    CheckConstraint("status IN ('active', 'disabled')", name="ck_account_status"),
    # A disabled account without a timestamp cannot answer "since when", which is the
    # first question asked when somebody complains they were locked out.
    CheckConstraint(
        "status <> 'disabled' OR disabled_at IS NOT NULL", name="ck_account_disabled_at"
    ),
)

plans = Table(
    "plans",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("code", String(64), nullable=False),
    Column("name", String(200), nullable=False),
    Column("status", String(32), nullable=False),
    Column("billing_interval", String(32), nullable=False),
    Column("external_product_reference", String(255)),
    Column("external_price_reference", String(255)),
    # A JSON array of corpus ids, not a foreign key: corpora are configuration owned by
    # the governance profile, not rows, and a plan that referenced a table nobody
    # populates would be unsellable for reasons no operator could see.
    Column("entitled_corpora_json", Text, nullable=False, default="[]"),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("code", name="uq_plans_code"),
    CheckConstraint("status IN ('active', 'retired')", name="ck_plan_status"),
    CheckConstraint("billing_interval IN ('monthly', 'yearly')", name="ck_plan_interval"),
)

subscriptions = Table(
    "subscriptions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column(
        "account_id",
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("plan_id", String(36), ForeignKey("plans.id"), nullable=False),
    Column("provider", String(64), nullable=False),
    Column("provider_customer_id", String(255)),
    Column("provider_subscription_id", String(255)),
    Column("status", String(32), nullable=False),
    Column("current_period_start", DateTime(timezone=True)),
    Column("current_period_end", DateTime(timezone=True)),
    Column("cancel_at_period_end", Boolean, nullable=False, default=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "status IN ('incomplete', 'active', 'past_due', 'canceled', 'expired')",
        name="ck_subscription_status",
    ),
    CheckConstraint(
        "current_period_end IS NULL OR current_period_start IS NULL "
        "OR current_period_end >= current_period_start",
        name="ck_subscription_period",
    ),
)

#: Partial: a subscription exists before the provider has assigned it an id, and several
#: of those legitimately carry NULL at once. Uniqueness applies to the ones that have one.
Index(
    "uq_subscription_provider_id",
    subscriptions.c.provider,
    subscriptions.c.provider_subscription_id,
    unique=True,
    sqlite_where=subscriptions.c.provider_subscription_id.isnot(None),
    postgresql_where=subscriptions.c.provider_subscription_id.isnot(None),
)

#: The entitlement read runs on every answer request. It asks for one account's
#: subscriptions in one status, which is the shape this covers.
Index("ix_subscriptions_account_status", subscriptions.c.account_id, subscriptions.c.status)

billing_events = Table(
    "billing_events",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("provider", String(64), nullable=False),
    Column("provider_event_id", String(255), nullable=False),
    Column("event_type", String(128), nullable=False),
    # The hash, never the body. A webhook payload carries names, emails and card
    # metadata; storing it would make this table a second place they leak from, and the
    # only question it has to answer is "have I seen this exact event before".
    Column("payload_hash", String(64), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("processed_at", DateTime(timezone=True)),
    Column("processing_result", String(32)),
    Column("subscription_id", String(36), ForeignKey("subscriptions.id", ondelete="SET NULL")),
    # The idempotency key, enforced by the database. A service that SELECTs first and
    # INSERTs second has a window, and a provider redelivering during that window is the
    # normal case, not the rare one.
    UniqueConstraint("provider", "provider_event_id", name="uq_billing_event_identity"),
    CheckConstraint(
        "processing_result IS NULL OR processing_result IN ('applied', 'duplicate', 'rejected')",
        name="ck_billing_event_result",
    ),
)

conversations = Table(
    "conversations",
    metadata,
    Column("id", String(36), primary_key=True),
    Column(
        "account_id",
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("title", String(200)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("archived_at", DateTime(timezone=True)),
)

#: Every conversation read is scoped by owner and ordered by recency. Listing without
#: this is a scan whose cost is invisible until one account has ten thousand of them.
Index("ix_conversations_owner", conversations.c.account_id, conversations.c.updated_at)

messages = Table(
    "messages",
    metadata,
    Column("id", String(36), primary_key=True),
    Column(
        "conversation_id",
        String(36),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    ),
    # 'user' or 'assistant'. The column exists so the evidence boundary is representable:
    # an assistant message is a sentence this system emitted, and reading it back as a
    # source would let the system cite itself.
    Column("role", String(32), nullable=False),
    Column("raw_text", Text, nullable=False),
    # A pointer to the answer, not a copy of it. The citations live in the answer path;
    # duplicating them here would create a second version of what the system said that
    # nothing keeps in step.
    Column("answer_id", String(36)),
    # The verdict as the reader saw it. Not recomputable later — the corpus moves, the
    # calibration moves, and the same question tomorrow may be refused — so a transcript
    # without it renders a refusal as though it were an answer.
    Column("answer_status", String(32)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("role IN ('user', 'assistant')", name="ck_message_role"),
)

Index("ix_messages_conversation", messages.c.conversation_id, messages.c.created_at)
