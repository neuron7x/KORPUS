"""accounts, plans, subscriptions, billing events, conversations and messages

ACT-001 puts a product around the answer kernel. Six tables arrive together because they
only make sense together: an account with no subscription cannot be denied for
non-payment, and a subscription with no billing event has no evidence for why it is in the
state it is in.

Forward-only in the sense that matters: the upgrade adds tables and touches none of the
existing ones, so a v6.0.0 database upgrades without rewriting a single corpus row, and a
failure here leaves the corpus exactly as it was. The downgrade drops the six in reverse
dependency order — offered so the upgrade can be rehearsed, and destructive if run against
anything real, which is true of every downgrade and worth saying once.

Three uniqueness constraints carry the safety properties, and all three are here rather
than in a service:

  ``uq_accounts_auth_subject``    two concurrent first logins cannot both create.
  ``uq_billing_event_identity``   a redelivered webhook cannot be applied twice.
  ``uq_subscription_provider_id`` partial, because a subscription exists before the
                                  provider has assigned it an id and several of those
                                  legitimately carry NULL at once.

Revision ID: 0012_tenancy
Revises: 0011_audit_key_id
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_tenancy"
down_revision: str | None = "0011_audit_key_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("auth_subject", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320)),
        sa.Column("display_name", sa.String(200)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("auth_subject", name="uq_accounts_auth_subject"),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_account_status"),
        sa.CheckConstraint(
            "status <> 'disabled' OR disabled_at IS NOT NULL", name="ck_account_disabled_at"
        ),
    )

    op.create_table(
        "plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("billing_interval", sa.String(32), nullable=False),
        sa.Column("external_product_reference", sa.String(255)),
        sa.Column("external_price_reference", sa.String(255)),
        sa.Column("entitled_corpora_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("code", name="uq_plans_code"),
        sa.CheckConstraint("status IN ('active', 'retired')", name="ck_plan_status"),
        sa.CheckConstraint("billing_interval IN ('monthly', 'yearly')", name="ck_plan_interval"),
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("plan_id", sa.String(36), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("provider_customer_id", sa.String(255)),
        sa.Column("provider_subscription_id", sa.String(255)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_period_start", sa.DateTime(timezone=True)),
        sa.Column("current_period_end", sa.DateTime(timezone=True)),
        sa.Column("cancel_at_period_end", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('incomplete', 'active', 'past_due', 'canceled', 'expired')",
            name="ck_subscription_status",
        ),
        sa.CheckConstraint(
            "current_period_end IS NULL OR current_period_start IS NULL "
            "OR current_period_end >= current_period_start",
            name="ck_subscription_period",
        ),
    )
    op.create_index("ix_subscriptions_account_id", "subscriptions", ["account_id"])
    op.create_index(
        "ix_subscriptions_account_status", "subscriptions", ["account_id", "status"]
    )
    op.create_index(
        "uq_subscription_provider_id",
        "subscriptions",
        ["provider", "provider_subscription_id"],
        unique=True,
        sqlite_where=sa.text("provider_subscription_id IS NOT NULL"),
        postgresql_where=sa.text("provider_subscription_id IS NOT NULL"),
    )

    op.create_table(
        "billing_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("provider_event_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("processing_result", sa.String(32)),
        sa.Column(
            "subscription_id",
            sa.String(36),
            sa.ForeignKey("subscriptions.id", ondelete="SET NULL"),
        ),
        sa.UniqueConstraint("provider", "provider_event_id", name="uq_billing_event_identity"),
        sa.CheckConstraint(
            "processing_result IS NULL "
            "OR processing_result IN ('applied', 'duplicate', 'rejected')",
            name="ck_billing_event_result",
        ),
    )

    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_conversations_owner", "conversations", ["account_id", "updated_at"])

    op.create_table(
        "messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(36),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Column("answer_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_message_role"),
    )
    op.create_index("ix_messages_conversation", "messages", ["conversation_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_messages_conversation", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_owner", table_name="conversations")
    op.drop_table("conversations")
    op.drop_table("billing_events")
    op.drop_index("uq_subscription_provider_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_account_status", table_name="subscriptions")
    op.drop_index("ix_subscriptions_account_id", table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_table("plans")
    op.drop_table("accounts")
