"""sellable plan pricing

A subscription can exist without a configured price for tests, free plans and operator
staging, but checkout cannot. Price therefore belongs to the plan and is nullable as a
pair: both ``price_minor`` and ``currency`` are present, or neither is. Integer minor
units avoid floating point money crossing the persistence boundary.

Revision ID: 0015_plan_pricing
Revises: 0014_subscription_last_event
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_plan_pricing"
down_revision: str | None = "0014_subscription_last_event"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plans", sa.Column("price_minor", sa.Integer()))
    op.add_column("plans", sa.Column("currency", sa.String(3)))
    with op.batch_alter_table("plans") as batch:
        batch.create_check_constraint(
            "ck_plan_price_positive", "price_minor IS NULL OR price_minor > 0"
        )
        batch.create_check_constraint(
            "ck_plan_price_currency_pair",
            "(price_minor IS NULL AND currency IS NULL) OR "
            "(price_minor IS NOT NULL AND currency IS NOT NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("plans") as batch:
        batch.drop_constraint("ck_plan_price_currency_pair", type_="check")
        batch.drop_constraint("ck_plan_price_positive", type_="check")
        batch.drop_column("currency")
        batch.drop_column("price_minor")
