"""governed capability side-effect ledger with subject-bound FORCE RLS.

Revision ID: 0024_capability_effect_ledger
Revises: 0023_evidence_search_vector

The table is product state, not telemetry or an adapter cache. A duplicate side effect can
be operationally irreversible, so the idempotency reservation must survive process restarts
and concurrent replicas. PostgreSQL additionally binds every visible/mutable row to the
non-forgeable RLS subject introduced by revision 0020.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_capability_effect_ledger"
down_revision: str | None = "0023_evidence_search_vector"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "capability_effects",
        sa.Column("subject_id", sa.String(length=256), nullable=False),
        sa.Column("idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("binding_digest", sa.String(length=71), nullable=False),
        sa.Column("invocation_id", sa.String(length=36), nullable=False),
        sa.Column("capability_id", sa.String(length=128), nullable=False),
        sa.Column("capability_version", sa.String(length=64), nullable=False),
        sa.Column("logical_resource", sa.String(length=512), nullable=False),
        sa.Column("input_digest", sa.String(length=71), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("provider_reference", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('PENDING','COMMITTED','FAILED_KNOWN_NO_EFFECT','OUTCOME_UNKNOWN','RECONCILED')",
            name="ck_capability_effect_state",
        ),
        sa.PrimaryKeyConstraint("subject_id", "idempotency_key"),
    )
    op.create_index(
        "ix_capability_effects_reconciliation",
        "capability_effects",
        ["state", "updated_at"],
        unique=False,
    )

    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute("ALTER TABLE capability_effects ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE capability_effects FORCE ROW LEVEL SECURITY")
    owner = "(subject_id = public.korpus_rls_subject())"
    op.execute(
        "CREATE POLICY capability_effect_select ON capability_effects "
        f"FOR SELECT USING ({owner})"
    )
    op.execute(
        "CREATE POLICY capability_effect_insert ON capability_effects "
        f"FOR INSERT WITH CHECK ({owner})"
    )
    op.execute(
        "CREATE POLICY capability_effect_update ON capability_effects "
        f"FOR UPDATE USING ({owner}) WITH CHECK ({owner})"
    )
    # There is intentionally no DELETE policy. Idempotency history is append/transition
    # state; ordinary runtime principals have no governed reason to erase it.


def downgrade() -> None:
    op.drop_index("ix_capability_effects_reconciliation", table_name="capability_effects")
    op.drop_table("capability_effects")
