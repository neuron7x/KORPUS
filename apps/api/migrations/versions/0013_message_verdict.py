"""a stored answer remembers whether it was one

Found by reading a conversation back in a browser. The transcript rendered both turns as
paragraphs of text, so a refusal — "У чинному перевіреному корпусі недостатньо доказів для
надійної відповіді" — looked exactly like an answer. Live, the same result gets ПІДСТАВИ
НЕМАЄ above it and a sentence saying an empty answer does not mean an empty corpus. Read
back, it got neither.

That is the one thing this interface has always refused to blur: a refusal is the system
working, and rendering it like an answer teaches a reader to skim past the difference. In
history the difference was not merely unrendered — it was not stored.

`answer_status` is the verdict at the moment the answer was given. Copying it here is not
the same as copying the citations: the citations belong to the answer and can be checked
against the corpus, while the verdict is a fact about what the reader was shown and cannot
be recomputed later — the corpus moves, the calibration moves, and the same question
answered tomorrow may be refused.

Nullable: every message written before this migration was written without a verdict, and
inventing one for them would be asserting what a reader saw. They render as "verdict not
recorded", which is what is true about them.

Revision ID: 0013_message_verdict
Revises: 0012_tenancy
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_message_verdict"
down_revision: str | None = "0012_tenancy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("answer_status", sa.String(32)))


def downgrade() -> None:
    op.drop_column("messages", "answer_status")
