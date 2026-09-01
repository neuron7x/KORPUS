"""approval provenance privilege boundary

Revision ID: 0022_approval_provenance_boundary
Revises: 0021_alembic_version_width

Затвердження — не дія застосунку. Поколонкові гранти вже забирають у
`korpus_app` право UPDATE на `review_state`, `evidence_digest`, посвідченнях,
`approved_*`, `is_current` і `documents.access_tier`. Але INSERT видається на
таблицю цілком, тож версію можна було НАРОДИТИ затвердженою й обійти весь
розділ прав однією вставкою.

Цей тригер закриває саме вставку. Портовано з GitHub-лінії з однією суттєвою
правкою: там перевірка членства — `pg_has_role(session_user, ..., 'MEMBER')`,
а для СУПЕРКОРИСТУВАЧА вона істинна для будь-якої ролі. Тобто тригер блокував
би й власника схеми — того, хто ставить фікстури й веде міграції. Тут членство
питається прямо в `pg_auth_members`: неявне членство суперкористувача туди не
потрапляє, і межа лишається межею саме для рантайму.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0022_approval_provenance_boundary"
down_revision: str | None = "0021_alembic_version_width"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GUARD = """
CREATE OR REPLACE FUNCTION public.korpus_guard_app_version_insert() RETURNS trigger AS $$
DECLARE is_app_runtime boolean;
BEGIN
  SELECT EXISTS (
    SELECT 1
    FROM pg_catalog.pg_auth_members m
    JOIN pg_catalog.pg_roles parent ON parent.oid = m.roleid
    JOIN pg_catalog.pg_roles member ON member.oid = m.member
    WHERE parent.rolname = 'korpus_app_runtime'
      AND member.rolname = session_user
  ) INTO is_app_runtime;
  IF is_app_runtime AND (
       NEW.review_state <> 'quarantined'
       OR NEW.evidence_digest IS NOT NULL
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
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public;
"""


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(_GUARD)
    op.execute("DROP TRIGGER IF EXISTS trg_korpus_guard_app_version_insert ON document_versions")
    op.execute(
        """
        CREATE TRIGGER trg_korpus_guard_app_version_insert
        BEFORE INSERT ON document_versions
        FOR EACH ROW EXECUTE FUNCTION public.korpus_guard_app_version_insert()
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP TRIGGER IF EXISTS trg_korpus_guard_app_version_insert ON document_versions")
    op.execute("DROP FUNCTION IF EXISTS public.korpus_guard_app_version_insert()")
