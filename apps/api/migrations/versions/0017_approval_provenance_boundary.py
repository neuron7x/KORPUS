"""approval provenance privilege boundary

Revision ID: 0017_approval_provenance_boundary
Revises: 0016a_alembic_version_width
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0017_approval_provenance_boundary"
down_revision: str | None = "0016a_alembic_version_width"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE OR REPLACE FUNCTION korpus_guard_app_version_insert() RETURNS trigger AS $$
        BEGIN
          IF pg_catalog.to_regrole('korpus_app_runtime') IS NOT NULL
             AND pg_catalog.pg_has_role(
               session_user, 'korpus_app_runtime', 'MEMBER'
             )
             AND (
               NEW.review_state <> 'quarantined'
               OR NEW.evidence_digest IS NOT NULL
               OR NEW.state_version <> 0
               OR NEW.near_duplicate_acknowledged_by IS NOT NULL
               OR NEW.extraction_quality_acknowledged_by IS NOT NULL
               OR NEW.metadata_reviewed_by IS NOT NULL
               OR NEW.metadata_reviewer_credential_id IS NOT NULL
               OR NEW.content_reviewed_by IS NOT NULL
               OR NEW.content_reviewer_credential_id IS NOT NULL
               OR NEW.approved_at IS NOT NULL
               OR NEW.approved_by IS NOT NULL
               OR NEW.approver_credential_id IS NOT NULL
               OR NEW.is_current
             ) THEN
            RAISE EXCEPTION 'application role cannot insert review-controlled state'
              USING ERRCODE = '42501';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql SET search_path = pg_catalog;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_korpus_guard_app_version_insert ON document_versions")
    op.execute(
        """
        CREATE TRIGGER trg_korpus_guard_app_version_insert
        BEFORE INSERT ON document_versions
        FOR EACH ROW EXECUTE FUNCTION korpus_guard_app_version_insert()
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP TRIGGER IF EXISTS trg_korpus_guard_app_version_insert ON document_versions")
    op.execute("DROP FUNCTION IF EXISTS korpus_guard_app_version_insert()")
