"""initial controlled-corpus schema

Revision ID: 0001_initial
Revises: None
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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
    )
    op.create_index("ix_documents_corpus_id", "documents", ["corpus_id"])
    op.create_table(
        "document_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.String(120), nullable=False),
        sa.Column("publication_identifier", sa.String(200)),
        sa.Column("source_uri", sa.Text()),
        sa.Column("source_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(200), nullable=False),
        sa.Column("publication_date", sa.Date()),
        sa.Column("effective_from", sa.Date()),
        sa.Column("effective_until", sa.Date()),
        sa.Column("rescinded_at", sa.DateTime(timezone=True)),
        sa.Column("authority", sa.String(64), nullable=False),
        sa.Column("review_state", sa.String(64), nullable=False),
        sa.Column("supersedes_version_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_document_versions_document_id", "document_versions", ["document_id"])
    op.create_index("ix_document_versions_source_hash", "document_versions", ["source_hash"], unique=True)
    op.create_table(
        "evidence_spans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version_id", sa.String(36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("page", sa.Integer()),
        sa.Column("section", sa.String(500)),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_evidence_spans_version_id", "evidence_spans", ["version_id"])
    op.create_table(
        "audit_events",
        sa.Column("sequence", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(36), nullable=False, unique=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_subject", sa.String(200), nullable=False),
        sa.Column("action", sa.String(200), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=False),
        sa.Column("resource_id", sa.String(200)),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("previous_hash", sa.String(64), nullable=False),
        sa.Column("event_hash", sa.String(64), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_index("ix_evidence_spans_version_id", table_name="evidence_spans")
    op.drop_table("evidence_spans")
    op.drop_index("ix_document_versions_source_hash", table_name="document_versions")
    op.drop_index("ix_document_versions_document_id", table_name="document_versions")
    op.drop_table("document_versions")
    op.drop_index("ix_documents_corpus_id", table_name="documents")
    op.drop_table("documents")
