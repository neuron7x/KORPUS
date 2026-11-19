"""Protect published learning lifecycle and both sides of relation reassignment.

Revision ID: 0026_learning_history_integrity
Revises: 0025_sealed_provenance_integrity

This restrictive migration is admitted for observed empty bootstrap only.
Existing installations require retirement proof; missing lifecycle history is
refused rather than reconstructed as a new draft.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0026_learning_history_integrity"
down_revision: str | None = "0025_sealed_provenance_integrity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _require_complete_lifecycle() -> None:
    orphan = (
        op.get_bind()
        .exec_driver_sql(
            "SELECT cv.id FROM learning_course_versions cv "
            "LEFT JOIN learning_publications p ON p.course_version_id = cv.id "
            "WHERE p.course_version_id IS NULL LIMIT 1"
        )
        .first()
    )
    if orphan is not None:
        raise RuntimeError(
            "LEARNING_HISTORY_REQUIRES_RECONCILIATION: missing publication lifecycle"
        )


def _install_postgres_guards() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.korpus_guard_learning_content_immutable()
        RETURNS trigger AS $$
        DECLARE old_version_id text;
        DECLARE new_version_id text;
        BEGIN
          IF TG_OP <> 'INSERT' THEN
            IF TG_TABLE_NAME = 'learning_course_versions' THEN old_version_id := OLD.id;
            ELSE old_version_id := OLD.course_version_id;
            END IF;
          END IF;
          IF TG_OP <> 'DELETE' THEN
            IF TG_TABLE_NAME = 'learning_course_versions' THEN new_version_id := NEW.id;
            ELSE new_version_id := NEW.course_version_id;
            END IF;
          END IF;
          IF EXISTS (
            SELECT 1 FROM public.learning_publications p
            WHERE p.course_version_id IN (old_version_id, new_version_id)
              AND p.state IN ('published', 'invalidated', 'retired')
          ) THEN
            RAISE EXCEPTION 'published learning history is immutable' USING ERRCODE = '42501';
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.korpus_guard_learning_course_identity()
        RETURNS trigger AS $$
        DECLARE old_course_id text;
        DECLARE new_course_id text;
        BEGIN
          old_course_id := OLD.id;
          IF TG_OP <> 'DELETE' THEN new_course_id := NEW.id; END IF;
          IF EXISTS (
            SELECT 1 FROM public.learning_course_versions cv
            JOIN public.learning_publications p ON p.course_version_id = cv.id
            WHERE cv.course_id IN (old_course_id, new_course_id)
              AND p.state IN ('published', 'invalidated', 'retired')
          ) THEN
            RAISE EXCEPTION 'course identity used by published history is immutable'
              USING ERRCODE = '42501';
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.korpus_guard_learning_lifecycle_identity()
        RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            IF OLD.state <> 'draft' THEN
              RAISE EXCEPTION 'published learning lifecycle is immutable'
                USING ERRCODE = '42501';
            END IF;
            RETURN OLD;
          END IF;
          IF NEW.course_version_id IS DISTINCT FROM OLD.course_version_id THEN
            RAISE EXCEPTION 'learning publication identity is immutable'
              USING ERRCODE = '42501';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION public.korpus_guard_learning_lifecycle_identity() FROM PUBLIC"
    )
    op.execute(
        "CREATE TRIGGER trg_korpus_guard_learning_lifecycle_identity "
        "BEFORE DELETE OR UPDATE OF course_version_id ON public.learning_publications "
        "FOR EACH ROW EXECUTE FUNCTION public.korpus_guard_learning_lifecycle_identity()"
    )


def _install_postgres_source_scope_guard() -> None:
    op.execute(
        """
        CREATE FUNCTION public.korpus_guard_learning_source_scope()
        RETURNS trigger AS $$
        BEGIN
          IF NEW.state = 'published' AND (TG_OP = 'INSERT' OR OLD.state = 'draft') THEN
            IF EXISTS (
              SELECT 1 FROM public.learning_source_bindings b
              WHERE b.course_version_id = NEW.course_version_id
                AND NOT EXISTS (
                  SELECT 1 FROM public.documents d WHERE d.id = b.document_id
                )
            ) THEN
              RAISE EXCEPTION 'course source is outside the authorized scope'
                USING ERRCODE = '42501';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog
        """
    )
    op.execute("REVOKE ALL ON FUNCTION public.korpus_guard_learning_source_scope() FROM PUBLIC")
    # PostgreSQL orders same-kind triggers by name: scope admission precedes the
    # SECURITY DEFINER structural guard and uses the caller's existing document RLS.
    op.execute(
        "CREATE TRIGGER trg_korpus_guard_learning_a_source_scope "
        "BEFORE INSERT OR UPDATE OF state, reviewed_at, reviewed_by "
        "ON public.learning_publications FOR EACH ROW "
        "EXECUTE FUNCTION public.korpus_guard_learning_source_scope()"
    )


def upgrade() -> None:
    _require_complete_lifecycle()
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        _install_postgres_guards()
        _install_postgres_source_scope_guard()
    elif dialect != "sqlite":
        raise RuntimeError("unsupported learning migration dialect")


def downgrade() -> None:
    raise RuntimeError(
        "learning history guard removal requires an independently retired deployment"
    )
