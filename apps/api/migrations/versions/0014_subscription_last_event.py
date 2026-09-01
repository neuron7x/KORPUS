"""a subscription remembers when its last applied event occurred

The replay guard compared an incoming event's provider timestamp against the
subscription's `updated_at`. But `updated_at` is our wall clock at the moment we processed
the previous event, and a provider's `occurred_at` is almost always earlier than when we
processed it — so a perfectly legitimate, correctly-ordered event could arrive with an
`occurred_at` that sits before `updated_at` and be rejected as a replay. A subscription
could jam on a single out-of-order-looking delivery and never advance again.

The guard has to compare like with like: the new event's `occurred_at` against the
`occurred_at` of the last event we actually applied. This column holds that. Nullable
because a subscription that has had no applied event has nothing to compare against — and
that absence means "accept", not "reject".

Revision ID: 0014_subscription_last_event
Revises: 0013_message_verdict
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_subscription_last_event"
down_revision: str | None = "0013_message_verdict"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("last_event_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "last_event_at")
