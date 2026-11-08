"""Prevent parent cascades and provenance rewrites after evidence is sealed.

Revision ID: 0025_sealed_provenance_integrity
Revises: 0024_capability_effect_ledger

The evidence-span DELETE trigger cannot protect against a foreign-key cascade:
PostgreSQL can remove the parent and all descendants without running the
independent authorization check intended for direct child DML. The seal is a
persistent fact even if the review state subsequently becomes rejected.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0025_sealed_provenance_integrity"
down_revision: str | None = "0024_capability_effect_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Fail before the implicit DELETE used by SQLite INSERT OR REPLACE. SQLite does
# not fire DELETE triggers for that deletion unless recursive_triggers is on.
_SQLITE_REPLACE_CONFLICT = """
EXISTS (
  SELECT 1 FROM document_versions
  WHERE evidence_digest IS NOT NULL AND (
    id = NEW.id OR (document_id = NEW.document_id AND revision = NEW.revision)
    OR (document_id = NEW.document_id AND is_current = 1 AND NEW.is_current = 1)
  )
)
"""


def _install_sqlite() -> None:
    op.execute(
        "CREATE TRIGGER trg_sealed_document_delete BEFORE DELETE ON documents "
        "WHEN EXISTS (SELECT 1 FROM document_versions WHERE document_id = OLD.id "
        "AND evidence_digest IS NOT NULL) "
        "BEGIN SELECT RAISE(ABORT, 'sealed document cannot be deleted'); END"
    )
    op.execute(
        "CREATE TRIGGER trg_sealed_version_delete BEFORE DELETE ON document_versions "
        "WHEN OLD.evidence_digest IS NOT NULL "
        "BEGIN SELECT RAISE(ABORT, 'sealed version cannot be deleted'); END"
    )
    op.execute(
        """
        CREATE TRIGGER trg_sealed_version_provenance_update
        BEFORE UPDATE OF document_id, revision, source_hash, object_key, authority, source_uri
        ON document_versions
        WHEN (OLD.evidence_digest IS NOT NULL OR NEW.evidence_digest IS NOT NULL)
         AND (NEW.document_id IS NOT OLD.document_id
           OR NEW.revision IS NOT OLD.revision
           OR NEW.source_hash IS NOT OLD.source_hash
           OR NEW.object_key IS NOT OLD.object_key
           OR NEW.authority IS NOT OLD.authority
           OR NEW.source_uri IS NOT OLD.source_uri)
        BEGIN SELECT RAISE(ABORT, 'sealed version provenance is immutable'); END
        """
    )
    op.execute(
        "CREATE TRIGGER trg_sealed_document_replace BEFORE INSERT ON documents "
        "WHEN EXISTS (SELECT 1 FROM document_versions WHERE document_id = NEW.id "
        "AND evidence_digest IS NOT NULL) "
        "BEGIN SELECT RAISE(ABORT, 'sealed document cannot be replaced'); END"
    )
    op.execute(
        "CREATE TRIGGER trg_sealed_version_replace BEFORE INSERT ON document_versions "
        f"WHEN {_SQLITE_REPLACE_CONFLICT} "
        "BEGIN SELECT RAISE(ABORT, 'sealed version cannot be replaced'); END"
    )
    op.execute(
        """
        CREATE TRIGGER trg_sealed_version_update_replace
        BEFORE UPDATE OF document_id, revision, is_current ON document_versions
        WHEN EXISTS (
          SELECT 1 FROM document_versions
          WHERE id != OLD.id AND evidence_digest IS NOT NULL
            AND ((document_id = NEW.document_id AND revision = NEW.revision)
              OR (document_id = NEW.document_id AND is_current = 1 AND NEW.is_current = 1))
        )
        BEGIN SELECT RAISE(ABORT, 'sealed version cannot be replaced'); END
        """
    )


def _install_postgres() -> None:
    op.execute(
        """
        CREATE FUNCTION public.korpus_guard_sealed_parent_delete() RETURNS trigger AS $$
        DECLARE child_sealed boolean;
        BEGIN
          IF TG_TABLE_NAME = 'document_versions' THEN
            IF OLD.evidence_digest IS NOT NULL THEN
              RAISE EXCEPTION 'sealed version cannot be deleted' USING ERRCODE = '23514';
            END IF;
          ELSE
            -- Lock every child, including drafts. Otherwise a concurrent approval
            -- could seal a draft after our check but before the FK cascade.
            FOR child_sealed IN
              SELECT evidence_digest IS NOT NULL
              FROM public.document_versions
              WHERE document_id = OLD.id
              ORDER BY id FOR UPDATE
            LOOP
              IF child_sealed THEN
                RAISE EXCEPTION 'sealed document cannot be deleted'
                  USING ERRCODE = '23514';
              END IF;
            END LOOP;
          END IF;
          RETURN OLD;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.korpus_guard_sealed_provenance_update() RETURNS trigger AS $$
        BEGIN
          IF (OLD.evidence_digest IS NOT NULL OR NEW.evidence_digest IS NOT NULL)
            AND ROW(OLD.document_id, OLD.revision, OLD.source_hash,
                    OLD.object_key, OLD.authority, OLD.source_uri)
                IS DISTINCT FROM
                ROW(NEW.document_id, NEW.revision, NEW.source_hash,
                    NEW.object_key, NEW.authority, NEW.source_uri)
          THEN
            RAISE EXCEPTION 'sealed version provenance is immutable'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql SET search_path = pg_catalog, public
        """
    )
    op.execute("REVOKE ALL ON FUNCTION public.korpus_guard_sealed_parent_delete() FROM PUBLIC")
    op.execute("REVOKE ALL ON FUNCTION public.korpus_guard_sealed_provenance_update() FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER trg_sealed_document_delete BEFORE DELETE ON documents "
        "FOR EACH ROW EXECUTE FUNCTION public.korpus_guard_sealed_parent_delete()"
    )
    op.execute(
        "CREATE TRIGGER trg_sealed_version_delete BEFORE DELETE ON document_versions "
        "FOR EACH ROW EXECUTE FUNCTION public.korpus_guard_sealed_parent_delete()"
    )
    op.execute(
        "CREATE TRIGGER trg_sealed_version_provenance_update "
        "BEFORE UPDATE OF document_id, revision, source_hash, object_key, authority, source_uri "
        "ON document_versions FOR EACH ROW "
        "EXECUTE FUNCTION public.korpus_guard_sealed_provenance_update()"
    )


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        _install_sqlite()
    elif dialect == "postgresql":
        _install_postgres()
    else:
        raise RuntimeError(f"unsupported migration dialect: {dialect}")


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for name in (
            "trg_sealed_version_update_replace",
            "trg_sealed_version_replace",
            "trg_sealed_document_replace",
            "trg_sealed_version_provenance_update",
            "trg_sealed_version_delete",
            "trg_sealed_document_delete",
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    elif dialect == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_sealed_version_provenance_update ON document_versions"
        )
        op.execute("DROP TRIGGER IF EXISTS trg_sealed_version_delete ON document_versions")
        op.execute("DROP TRIGGER IF EXISTS trg_sealed_document_delete ON documents")
        op.execute("DROP FUNCTION IF EXISTS public.korpus_guard_sealed_provenance_update()")
        op.execute("DROP FUNCTION IF EXISTS public.korpus_guard_sealed_parent_delete()")
    else:
        raise RuntimeError(f"unsupported migration dialect: {dialect}")
