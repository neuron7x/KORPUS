"""Physical schema for durable ingestion jobs.

Separated from the core document schema so ingestion persistence can be imported by
its adapter without creating a repository/adapter cycle. It shares the same MetaData.
"""
from sqlalchemy import Column, DateTime, Index, Integer, String, Table, Text

from korpus.infrastructure.schema import metadata

ingestion_jobs = Table(
    "ingestion_jobs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("kind", String(32), nullable=False),
    Column("actor_subject", String(200), nullable=False, index=True),
    Column("actor_json", Text, nullable=False),
    Column("document_json", Text),
    Column("document_id", String(36)),
    Column("version_json", Text, nullable=False),
    Column("filename", String(500), nullable=False),
    Column("mime_type", String(200), nullable=False),
    Column("source_hash", String(64), nullable=False),
    Column("staging_object_key", Text, nullable=False),
    Column("state", String(32), nullable=False, index=True),
    Column("attempts", Integer, nullable=False),
    Column("max_attempts", Integer, nullable=False),
    Column("lease_owner", String(200)),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("result_json", Text),
    Column("error_code", String(200)),
    Column("error_detail", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
Index(
    "ix_ingestion_jobs_claim",
    ingestion_jobs.c.state,
    ingestion_jobs.c.lease_expires_at,
    ingestion_jobs.c.created_at,
)
