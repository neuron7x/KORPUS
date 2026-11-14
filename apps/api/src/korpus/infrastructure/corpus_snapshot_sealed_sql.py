"""Pinned 0025 seal-guard SQL for metadata-created schemas and startup verification.

The migration remains self-contained; parity is exercised against its actual DDL.
"""

from __future__ import annotations

SQLITE_TRIGGERS = {
    "trg_sealed_document_delete": """
CREATE TRIGGER trg_sealed_document_delete BEFORE DELETE ON documents WHEN EXISTS (SELECT 1 FROM document_versions WHERE document_id = OLD.id AND evidence_digest IS NOT NULL) BEGIN SELECT RAISE(ABORT, 'sealed document cannot be deleted'); END
    """,
    "trg_sealed_version_delete": """
CREATE TRIGGER trg_sealed_version_delete BEFORE DELETE ON document_versions WHEN OLD.evidence_digest IS NOT NULL BEGIN SELECT RAISE(ABORT, 'sealed version cannot be deleted'); END
    """,
    "trg_sealed_version_provenance_update": """
CREATE TRIGGER trg_sealed_version_provenance_update
        BEFORE UPDATE OF id, document_id, revision, source_hash, object_key, authority, source_uri
        ON document_versions
        WHEN (OLD.evidence_digest IS NOT NULL OR NEW.evidence_digest IS NOT NULL)
         AND (NEW.id IS NOT OLD.id
           OR NEW.document_id IS NOT OLD.document_id
           OR NEW.revision IS NOT OLD.revision
           OR NEW.source_hash IS NOT OLD.source_hash
           OR NEW.object_key IS NOT OLD.object_key
           OR NEW.authority IS NOT OLD.authority
           OR NEW.source_uri IS NOT OLD.source_uri)
        BEGIN SELECT RAISE(ABORT, 'sealed version provenance is immutable'); END
    """,
    "trg_sealed_document_replace": """
CREATE TRIGGER trg_sealed_document_replace BEFORE INSERT ON documents WHEN EXISTS (SELECT 1 FROM document_versions WHERE document_id = NEW.id AND evidence_digest IS NOT NULL) BEGIN SELECT RAISE(ABORT, 'sealed document cannot be replaced'); END
    """,
    "trg_sealed_version_replace": """
CREATE TRIGGER trg_sealed_version_replace BEFORE INSERT ON document_versions WHEN
EXISTS (
  SELECT 1 FROM document_versions
  WHERE evidence_digest IS NOT NULL AND (
    id = NEW.id OR (document_id = NEW.document_id AND revision = NEW.revision)
    OR (document_id = NEW.document_id AND is_current = 1 AND NEW.is_current = 1)
  )
)
 BEGIN SELECT RAISE(ABORT, 'sealed version cannot be replaced'); END
    """,
    "trg_sealed_version_update_replace": """
CREATE TRIGGER trg_sealed_version_update_replace
        BEFORE UPDATE OF id, document_id, revision, is_current ON document_versions
        WHEN EXISTS (
          SELECT 1 FROM document_versions
          WHERE id != OLD.id AND evidence_digest IS NOT NULL
            AND (id = NEW.id
              OR (document_id = NEW.document_id AND revision = NEW.revision)
              OR (document_id = NEW.document_id AND is_current = 1 AND NEW.is_current = 1))
        )
        BEGIN SELECT RAISE(ABORT, 'sealed version cannot be replaced'); END
    """,
}

POSTGRES_FUNCTIONS = {
    "korpus_guard_sealed_parent_delete": """
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
    """,
    "korpus_guard_sealed_provenance_update": """
CREATE FUNCTION public.korpus_guard_sealed_provenance_update() RETURNS trigger AS $$
        BEGIN
          IF (OLD.evidence_digest IS NOT NULL OR NEW.evidence_digest IS NOT NULL)
            AND ROW(OLD.id, OLD.document_id, OLD.revision, OLD.source_hash,
                    OLD.object_key, OLD.authority, OLD.source_uri)
                IS DISTINCT FROM
                ROW(NEW.id, NEW.document_id, NEW.revision, NEW.source_hash,
                    NEW.object_key, NEW.authority, NEW.source_uri)
          THEN
            RAISE EXCEPTION 'sealed version provenance is immutable'
              USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql SET search_path = pg_catalog, public
    """,
}

POSTGRES_TRIGGERS = {
    ("documents", "trg_sealed_document_delete"): """
CREATE TRIGGER trg_sealed_document_delete BEFORE DELETE ON documents FOR EACH ROW EXECUTE FUNCTION public.korpus_guard_sealed_parent_delete()
    """,
    ("document_versions", "trg_sealed_version_delete"): """
CREATE TRIGGER trg_sealed_version_delete BEFORE DELETE ON document_versions FOR EACH ROW EXECUTE FUNCTION public.korpus_guard_sealed_parent_delete()
    """,
    ("document_versions", "trg_sealed_version_provenance_update"): """
CREATE TRIGGER trg_sealed_version_provenance_update BEFORE UPDATE OF id, document_id, revision, source_hash, object_key, authority, source_uri ON document_versions FOR EACH ROW EXECUTE FUNCTION public.korpus_guard_sealed_provenance_update()
    """,
}
