"""PostgreSQL installation of epoch and evidence guards for dev schemas."""

from __future__ import annotations

from sqlalchemy import text as sql_text
from sqlalchemy.engine import Connection

from korpus.infrastructure.corpus_snapshot_guards import EPOCH_TABLES
from korpus.infrastructure.corpus_snapshot_sealed_guards import install_sealed_guards


def _install_epoch(connection: Connection) -> None:
    connection.execute(
        sql_text(
            """
            CREATE OR REPLACE FUNCTION korpus_bump_corpus_state_epoch() RETURNS trigger AS $$
            BEGIN
              UPDATE public.corpus_state_epoch SET epoch = epoch + 1 WHERE singleton_id = 1;
              RETURN NULL;
            END;
            $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
            """
        )
    )
    for table in EPOCH_TABLES:
        name = f"trg_{table}_epoch"
        connection.execute(sql_text(f"DROP TRIGGER IF EXISTS {name} ON {table}"))
        connection.execute(
            sql_text(
                f"CREATE TRIGGER {name} AFTER INSERT OR UPDATE OR DELETE ON {table} "
                "FOR EACH STATEMENT EXECUTE FUNCTION korpus_bump_corpus_state_epoch()"
            )
        )


def _install_evidence(connection: Connection) -> None:
    connection.execute(
        sql_text(
            """
            CREATE OR REPLACE FUNCTION korpus_refuse_approved_evidence_mutation()
            RETURNS trigger AS $$
            DECLARE
              locked_digest text;
            BEGIN
              IF TG_OP = 'INSERT' THEN
                SELECT evidence_digest INTO locked_digest
                FROM public.document_versions
                WHERE id = NEW.version_id
                FOR SHARE;
                IF locked_digest IS NOT NULL THEN
                  RAISE EXCEPTION 'sealed evidence is immutable';
                END IF;
              ELSIF TG_OP = 'DELETE' THEN
                SELECT evidence_digest INTO locked_digest
                FROM public.document_versions
                WHERE id = OLD.version_id
                FOR SHARE;
                IF locked_digest IS NOT NULL THEN
                  RAISE EXCEPTION 'sealed evidence is immutable';
                END IF;
              ELSE
                FOR locked_digest IN
                  SELECT evidence_digest
                  FROM public.document_versions
                  WHERE id IN (OLD.version_id, NEW.version_id)
                  ORDER BY id
                  FOR SHARE
                LOOP
                  IF locked_digest IS NOT NULL THEN
                    RAISE EXCEPTION 'sealed evidence is immutable';
                  END IF;
                END LOOP;
              END IF;
              IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog
            """
        )
    )
    connection.execute(
        sql_text("REVOKE ALL ON FUNCTION korpus_refuse_approved_evidence_mutation() FROM PUBLIC")
    )
    connection.execute(
        sql_text("DROP TRIGGER IF EXISTS trg_evidence_spans_immutable ON evidence_spans")
    )
    connection.execute(
        sql_text(
            "CREATE TRIGGER trg_evidence_spans_immutable "
            "BEFORE INSERT OR UPDATE OR DELETE ON evidence_spans "
            "FOR EACH ROW EXECUTE FUNCTION korpus_refuse_approved_evidence_mutation()"
        )
    )


def _install_digest(connection: Connection) -> None:
    connection.execute(
        sql_text(
            """
            CREATE OR REPLACE FUNCTION korpus_refuse_approved_digest_mutation()
            RETURNS trigger AS $$
            BEGIN
              IF OLD.evidence_digest IS NOT NULL
                 AND NEW.evidence_digest IS DISTINCT FROM OLD.evidence_digest THEN
                RAISE EXCEPTION 'sealed evidence digest is immutable';
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
    )
    connection.execute(
        sql_text(
            "DROP TRIGGER IF EXISTS trg_approved_version_digest_immutable ON document_versions"
        )
    )
    connection.execute(
        sql_text(
            "CREATE TRIGGER trg_approved_version_digest_immutable "
            "BEFORE UPDATE OF evidence_digest ON document_versions "
            "FOR EACH ROW EXECUTE FUNCTION korpus_refuse_approved_digest_mutation()"
        )
    )


def install_postgres_guards(connection: Connection) -> None:
    _install_epoch(connection)
    _install_evidence(connection)
    _install_digest(connection)
    install_sealed_guards(connection)
