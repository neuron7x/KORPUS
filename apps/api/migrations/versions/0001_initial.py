"""research-grade controlled-corpus schema

Revision ID: 0001_initial
Revises: None
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("canonical_title", sa.String(500), nullable=False),
        sa.Column("corpus_id", sa.String(64), nullable=False),
        sa.Column("issuer", sa.String(300), nullable=False),
        sa.Column("jurisdiction", sa.String(50), nullable=False),
        sa.Column("document_type", sa.String(100), nullable=False),
        sa.Column("access_tier", sa.Integer(), nullable=False),
        sa.Column("classification", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("access_tier >= 0 AND access_tier <= 3", name="ck_document_access_tier"),
    )
    op.create_index("ix_documents_corpus_id", "documents", ["corpus_id"])

    op.create_table(
        "document_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision", sa.String(120), nullable=False),
        sa.Column("publication_identifier", sa.String(200)),
        sa.Column("source_uri", sa.Text()),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(200), nullable=False),
        sa.Column("publication_date", sa.Date()),
        sa.Column("effective_from", sa.Date()),
        sa.Column("effective_until", sa.Date()),
        sa.Column("rescinded_at", sa.DateTime(timezone=True)),
        sa.Column("authority", sa.String(64), nullable=False),
        sa.Column("review_state", sa.String(64), nullable=False),
        sa.Column(
            "supersedes_version_id",
            sa.String(36),
            sa.ForeignKey("document_versions.id"),
        ),
        sa.Column("state_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata_reviewed_by", sa.String(200)),
        sa.Column("content_reviewed_by", sa.String(200)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by", sa.String(200)),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_id", "source_hash", name="uq_version_document_source_hash"),
        sa.CheckConstraint("state_version >= 0", name="ck_version_state_version"),
    )
    op.create_index("ix_document_versions_document_id", "document_versions", ["document_id"])
    op.create_index("ix_document_versions_source_hash", "document_versions", ["source_hash"])
    op.create_index("ix_document_versions_is_current", "document_versions", ["is_current"])

    op.create_table(
        "evidence_spans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "version_id",
            sa.String(36),
            sa.ForeignKey("document_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("page", sa.Integer()),
        sa.Column("section", sa.String(500)),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("version_id", "ordinal", name="uq_span_version_ordinal"),
    )
    op.create_index("ix_evidence_spans_version_id", "evidence_spans", ["version_id"])
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute(
            "CREATE VIRTUAL TABLE evidence_fts "
            "USING fts5(span_id UNINDEXED, text, tokenize='unicode61 remove_diacritics 2')"
        )
    elif dialect == "postgresql":
        op.execute(
            "CREATE INDEX ix_evidence_spans_search "
            "ON evidence_spans USING GIN (to_tsvector('simple', text))"
        )

    op.create_table(
        "audit_heads",
        sa.Column("singleton_id", sa.Integer(), primary_key=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("head_hash", sa.String(64), nullable=False),
        sa.CheckConstraint("singleton_id = 1", name="ck_audit_head_singleton"),
    )
    op.bulk_insert(
        sa.table(
            "audit_heads",
            sa.column("singleton_id", sa.Integer()),
            sa.column("sequence", sa.Integer()),
            sa.column("head_hash", sa.String(64)),
        ),
        [{"singleton_id": 1, "sequence": 0, "head_hash": "0" * 64}],
    )

    op.create_table(
        "audit_events",
        sa.Column("sequence", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False, unique=True),
        sa.Column("event_schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_subject", sa.String(200), nullable=False),
        sa.Column("action", sa.String(200), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=False),
        sa.Column("resource_id", sa.String(200)),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("previous_hash", sa.String(64), nullable=False),
        sa.Column("event_hash", sa.String(64), nullable=False),
    )
    op.create_table(
        "audit_anchor_outbox",
        sa.Column(
            "sequence",
            sa.Integer(),
            sa.ForeignKey("audit_events.sequence", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("head_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("DROP TABLE IF EXISTS evidence_fts")
    elif dialect == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_evidence_spans_search")
    op.drop_table("audit_anchor_outbox")
    op.drop_table("audit_events")
    op.drop_table("audit_heads")
    op.drop_index("ix_evidence_spans_version_id", table_name="evidence_spans")
    op.drop_table("evidence_spans")
    op.drop_index("ix_document_versions_is_current", table_name="document_versions")
    op.drop_index("ix_document_versions_source_hash", table_name="document_versions")
    op.drop_index("ix_document_versions_document_id", table_name="document_versions")
    op.drop_table("document_versions")
    op.drop_index("ix_documents_corpus_id", table_name="documents")
    op.drop_table("documents")
