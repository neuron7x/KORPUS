"""persist immutable learning course graph

Revision ID: 0020_learning_course_graph
Revises: 0019_rls_binding_backend_identity
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from korpus.infrastructure.learning_schema import LEARNING_TABLES

revision: str = "0020_learning_course_graph"
down_revision: str | None = "0019_rls_binding_backend_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONTENT_TABLES = (
    "learning_course_versions",
    "learning_modules",
    "learning_lessons",
    "learning_objectives",
    "learning_source_bindings",
    "learning_source_binding_spans",
    "learning_lesson_blocks",
    "learning_block_sources",
    "learning_prerequisites",
)


def _install_postgres_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION korpus_guard_published_learning_content() RETURNS trigger AS $$
        DECLARE version_id text;
        BEGIN
          IF TG_TABLE_NAME = 'learning_course_versions' THEN
            IF TG_OP = 'DELETE' THEN version_id := OLD.id; ELSE version_id := NEW.id; END IF;
          ELSE
            IF TG_OP = 'DELETE' THEN
              version_id := OLD.course_version_id;
            ELSE
              version_id := NEW.course_version_id;
            END IF;
          END IF;
          IF EXISTS (
            SELECT 1 FROM public.learning_publications p
            WHERE p.course_version_id = version_id AND p.state = 'published'
          ) THEN
            RAISE EXCEPTION 'published course content is immutable' USING ERRCODE = '42501';
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
        """
    )
    op.execute("REVOKE ALL ON FUNCTION korpus_guard_published_learning_content() FROM PUBLIC")
    for table in _CONTENT_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_korpus_guard_{table} "
            f"BEFORE INSERT OR UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION korpus_guard_published_learning_content()"
        )

    op.execute(
        """
        CREATE FUNCTION korpus_guard_learning_publication() RETURNS trigger AS $$
        DECLARE has_cycle boolean;
        BEGIN
          IF NEW.state <> 'published' THEN RETURN NEW; END IF;
          IF NEW.reviewed_at IS NULL OR NEW.reviewed_by IS NULL OR NEW.reviewed_by = '' THEN
            RAISE EXCEPTION 'published course requires review identity' USING ERRCODE = '23514';
          END IF;
          IF NOT EXISTS (
            SELECT 1 FROM public.learning_modules m
            WHERE m.course_version_id = NEW.course_version_id
          ) OR NOT EXISTS (
            SELECT 1 FROM public.learning_lessons l
            WHERE l.course_version_id = NEW.course_version_id
          ) THEN
            RAISE EXCEPTION 'published course requires modules and lessons' USING ERRCODE = '23514';
          END IF;
          IF EXISTS (
            SELECT 1 FROM public.learning_lessons l
            WHERE l.course_version_id = NEW.course_version_id
              AND (
                NOT EXISTS (
                  SELECT 1 FROM public.learning_objectives o
                  WHERE o.course_version_id = l.course_version_id AND o.lesson_id = l.id
                )
                OR NOT EXISTS (
                  SELECT 1 FROM public.learning_source_bindings b
                  WHERE b.course_version_id = l.course_version_id AND b.lesson_id = l.id
                )
                OR NOT EXISTS (
                  SELECT 1 FROM public.learning_lesson_blocks bl
                  WHERE bl.course_version_id = l.course_version_id AND bl.lesson_id = l.id
                )
              )
          ) THEN
            RAISE EXCEPTION 'published lesson is structurally incomplete' USING ERRCODE = '23514';
          END IF;
          IF EXISTS (
            SELECT 1
            FROM public.learning_source_bindings b
            LEFT JOIN public.document_versions v ON v.id = b.version_id
            WHERE b.course_version_id = NEW.course_version_id
              AND (
                v.id IS NULL
                OR v.document_id <> b.document_id
                OR v.review_state <> 'approved'
                OR v.rescinded_at IS NOT NULL
                OR (v.effective_from IS NOT NULL AND v.effective_from > CURRENT_DATE)
                OR (v.effective_until IS NOT NULL AND v.effective_until < CURRENT_DATE)
              )
          ) THEN
            RAISE EXCEPTION 'course source is not approved/effective' USING ERRCODE = '23514';
          END IF;
          IF EXISTS (
            SELECT 1
            FROM public.learning_source_binding_spans s
            JOIN public.learning_source_bindings b
              ON b.course_version_id = s.course_version_id
             AND b.lesson_id = s.lesson_id
             AND b.id = s.binding_id
            LEFT JOIN public.evidence_spans e
              ON e.id = s.span_id AND e.version_id = b.version_id
            WHERE s.course_version_id = NEW.course_version_id AND e.id IS NULL
          ) THEN
            RAISE EXCEPTION 'course evidence span does not belong to bound version'
              USING ERRCODE = '23514';
          END IF;
          IF EXISTS (
            SELECT 1 FROM public.learning_source_bindings b
            WHERE b.course_version_id = NEW.course_version_id
              AND NOT EXISTS (
                SELECT 1 FROM public.learning_source_binding_spans s
                WHERE s.course_version_id = b.course_version_id
                  AND s.lesson_id = b.lesson_id AND s.binding_id = b.id
              )
          ) THEN
            RAISE EXCEPTION 'course source binding requires evidence spans' USING ERRCODE = '23514';
          END IF;
          WITH RECURSIVE walk(start_id, current_id, path, cycle) AS (
            SELECT p.lesson_id, p.prerequisite_lesson_id,
                   ARRAY[p.lesson_id, p.prerequisite_lesson_id]::text[],
                   p.lesson_id = p.prerequisite_lesson_id
            FROM public.learning_prerequisites p
            WHERE p.course_version_id = NEW.course_version_id
            UNION ALL
            SELECT w.start_id, p.prerequisite_lesson_id,
                   w.path || p.prerequisite_lesson_id,
                   p.prerequisite_lesson_id = ANY(w.path)
            FROM walk w
            JOIN public.learning_prerequisites p
              ON p.course_version_id = NEW.course_version_id
             AND p.lesson_id = w.current_id
            WHERE NOT w.cycle
          )
          SELECT COALESCE(bool_or(cycle), false) INTO has_cycle FROM walk;
          IF has_cycle THEN
            RAISE EXCEPTION 'course prerequisite graph contains a cycle' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
        """
    )
    op.execute("REVOKE ALL ON FUNCTION korpus_guard_learning_publication() FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER trg_korpus_guard_learning_publication "
        "BEFORE INSERT OR UPDATE OF state, reviewed_at, reviewed_by ON learning_publications "
        "FOR EACH ROW EXECUTE FUNCTION korpus_guard_learning_publication()"
    )

    op.execute(
        """
        CREATE FUNCTION korpus_invalidate_learning_publications() RETURNS trigger AS $$
        BEGIN
          IF NEW.review_state <> 'approved'
             OR NEW.rescinded_at IS NOT NULL
             OR (NEW.effective_from IS NOT NULL AND NEW.effective_from > CURRENT_DATE)
             OR (NEW.effective_until IS NOT NULL AND NEW.effective_until < CURRENT_DATE) THEN
            UPDATE public.learning_publications p
            SET state = 'invalidated', updated_at = CURRENT_TIMESTAMP
            WHERE p.state = 'published'
              AND EXISTS (
                SELECT 1 FROM public.learning_source_bindings b
                WHERE b.course_version_id = p.course_version_id AND b.version_id = NEW.id
              );
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
        """
    )
    op.execute("REVOKE ALL ON FUNCTION korpus_invalidate_learning_publications() FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER trg_korpus_invalidate_learning_publications "
        "AFTER UPDATE OF review_state, rescinded_at, effective_from, effective_until "
        "ON document_versions FOR EACH ROW "
        "EXECUTE FUNCTION korpus_invalidate_learning_publications()"
    )


def upgrade() -> None:
    bind = op.get_bind()
    for table in LEARNING_TABLES:
        table.create(bind, checkfirst=False)
    if bind.dialect.name == "postgresql":
        _install_postgres_guards()


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_korpus_invalidate_learning_publications ON document_versions"
        )
        op.execute("DROP FUNCTION IF EXISTS korpus_invalidate_learning_publications()")
        op.execute(
            "DROP TRIGGER IF EXISTS trg_korpus_guard_learning_publication ON learning_publications"
        )
        op.execute("DROP FUNCTION IF EXISTS korpus_guard_learning_publication()")
        for table in reversed(_CONTENT_TABLES):
            op.execute(f"DROP TRIGGER IF EXISTS trg_korpus_guard_{table} ON {table}")
        op.execute("DROP FUNCTION IF EXISTS korpus_guard_published_learning_content()")
    for table in reversed(LEARNING_TABLES):
        table.drop(bind, checkfirst=False)
