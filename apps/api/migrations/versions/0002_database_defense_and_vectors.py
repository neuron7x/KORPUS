"""database defense-in-depth and semantic index substrate

Revision ID: 0002_database_defense_and_vectors
Revises: 0001_initial
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_database_defense_and_vectors"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "span_embeddings",
        sa.Column("span_id", sa.String(36), sa.ForeignKey("evidence_spans.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("model_id", sa.String(200), primary_key=True),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding_json", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("dimensions > 0", name="ck_span_embedding_dimensions"),
    )
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute("ALTER TABLE span_embeddings ADD COLUMN embedding_vector vector")
        op.execute("ALTER TABLE evidence_spans ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE evidence_spans FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY evidence_span_authorized_select ON evidence_spans FOR SELECT USING (
                EXISTS (
                    SELECT 1 FROM document_versions v
                    JOIN documents d ON d.id = v.document_id
                    WHERE v.id = evidence_spans.version_id
                      AND d.access_tier <= COALESCE(NULLIF(current_setting('korpus.clearance', true), ''), '-1')::int
                      AND d.corpus_id = ANY(string_to_array(COALESCE(current_setting('korpus.corpora', true), ''), ','))
                      AND d.classification = ANY(string_to_array(COALESCE(current_setting('korpus.classifications', true), ''), ','))
                )
            )
            """
        )
        op.execute("CREATE POLICY evidence_span_insert ON evidence_spans FOR INSERT WITH CHECK (true)")
        op.execute("CREATE POLICY evidence_span_update ON evidence_spans FOR UPDATE USING (true) WITH CHECK (true)")
        op.execute("CREATE POLICY evidence_span_delete ON evidence_spans FOR DELETE USING (true)")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS evidence_span_delete ON evidence_spans")
        op.execute("DROP POLICY IF EXISTS evidence_span_update ON evidence_spans")
        op.execute("DROP POLICY IF EXISTS evidence_span_insert ON evidence_spans")
        op.execute("DROP POLICY IF EXISTS evidence_span_authorized_select ON evidence_spans")
        op.execute("ALTER TABLE evidence_spans DISABLE ROW LEVEL SECURITY")
    op.drop_table("span_embeddings")
