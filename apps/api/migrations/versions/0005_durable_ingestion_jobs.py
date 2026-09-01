"""durable ingestion job queue

Revision ID: 0005_durable_ingestion_jobs
Revises: 0004_compartmented_authorization
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_durable_ingestion_jobs"
down_revision: str | None = "0004_compartmented_authorization"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _roles() -> str:
    return "string_to_array(COALESCE(current_setting('korpus.roles', true), ''), ',')"


def upgrade() -> None:
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("actor_subject", sa.String(length=200), nullable=False),
        sa.Column("actor_json", sa.Text(), nullable=False),
        sa.Column("document_json", sa.Text()),
        sa.Column("document_id", sa.String(length=36)),
        sa.Column("version_json", sa.Text(), nullable=False),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=200), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("staging_object_key", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(length=200)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("result_json", sa.Text()),
        sa.Column("error_code", sa.String(length=200)),
        sa.Column("error_detail", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempts >= 0 AND max_attempts >= 1", name="ck_ingestion_job_attempts"),
        sa.CheckConstraint(
            "state IN ('queued','running','succeeded','retryable','dead_letter')",
            name="ck_ingestion_job_state",
        ),
        sa.CheckConstraint(
            "(kind = 'document' AND document_json IS NOT NULL AND document_id IS NULL) OR "
            "(kind = 'version' AND document_json IS NULL AND document_id IS NOT NULL)",
            name="ck_ingestion_job_target",
        ),
    )
    op.create_index("ix_ingestion_jobs_actor_subject", "ingestion_jobs", ["actor_subject"])
    op.create_index("ix_ingestion_jobs_state", "ingestion_jobs", ["state"])
    op.create_index(
        "ix_ingestion_jobs_claim",
        "ingestion_jobs",
        ["state", "lease_expires_at", "created_at"],
    )

    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE ingestion_jobs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ingestion_jobs FORCE ROW LEVEL SECURITY")
    subject = "COALESCE(current_setting('korpus.subject', true), '')"
    roles = _roles()
    visible = (
        f"actor_subject = {subject} OR 'admin' = ANY({roles}) OR "
        f"'auditor' = ANY({roles}) OR 'worker' = ANY({roles})"
    )
    op.execute(f"CREATE POLICY ingestion_job_select ON ingestion_jobs FOR SELECT USING ({visible})")
    op.execute(
        "CREATE POLICY ingestion_job_insert ON ingestion_jobs FOR INSERT WITH CHECK ("
        f"actor_subject = {subject} AND ('admin' = ANY({roles}) OR 'curator' = ANY({roles})))"
    )
    op.execute(
        "CREATE POLICY ingestion_job_update ON ingestion_jobs FOR UPDATE USING ("
        f"'admin' = ANY({roles}) OR 'worker' = ANY({roles})) WITH CHECK ("
        f"'admin' = ANY({roles}) OR 'worker' = ANY({roles}))"
    )
    op.execute(
        "CREATE POLICY ingestion_job_delete ON ingestion_jobs FOR DELETE USING "
        f"('admin' = ANY({roles}))"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for policy in (
            "ingestion_job_delete",
            "ingestion_job_update",
            "ingestion_job_insert",
            "ingestion_job_select",
        ):
            op.execute(f"DROP POLICY IF EXISTS {policy} ON ingestion_jobs")
        op.execute("ALTER TABLE ingestion_jobs DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_ingestion_jobs_claim", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_state", table_name="ingestion_jobs")
    op.drop_index("ix_ingestion_jobs_actor_subject", table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
