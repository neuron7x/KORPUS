"""an audit event records which key signed it

Every event was signed with one key and verified with whatever key the process held, so
rotating the key invalidated the entire history at once: the verifier recomputes each
event's HMAC and with a new key none of them match. The only way to change the key was to
stop being able to prove anything that had happened.

The column is filled with `legacy-unversioned` for existing rows rather than left NULL.
They were all signed with the one key the deployment had, and giving that key a name is
what lets them keep verifying after a rotation instead of becoming unattributable. A NULL
would mean "unknown", which is a different and false statement about them.

Not nullable going forward: an event that does not say which key signed it cannot be
verified after the first rotation, and an unverifiable event in an append-only chain is
indistinguishable from a forged one.

Revision ID: 0011_audit_key_id
Revises: 0010_revision_identity
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_audit_key_id"
down_revision: str | None = "0010_revision_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY = "legacy-unversioned"


def upgrade() -> None:
    op.add_column(
        "audit_events",
        sa.Column("audit_key_id", sa.String(64), nullable=False, server_default=LEGACY),
    )
    op.create_index("ix_audit_events_key_id", "audit_events", ["audit_key_id"])


def downgrade() -> None:
    # Downgrading loses which key signed what, which is exactly the state this migration
    # exists to leave. It is offered because a migration that cannot be reversed cannot be
    # rehearsed, and rehearsing it is how anyone learns the cost before paying it.
    op.drop_index("ix_audit_events_key_id", table_name="audit_events")
    op.drop_column("audit_events", "audit_key_id")
