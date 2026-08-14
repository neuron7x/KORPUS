"""SQL implementation of one immutable, epoch-bound corpus read token."""
from __future__ import annotations

from datetime import date

from sqlalchemy import insert, select
from sqlalchemy import text as sql_text
from sqlalchemy.engine import Connection

from korpus.application.corpus_snapshot import (
    CorpusConsistencyError,
    CorpusReadToken,
    authorization_scope_id,
    release_identity_digest,
)
from korpus.domain.models import Identity
from korpus.infrastructure import retrieval_queries
from korpus.infrastructure.corpus_snapshot_guards import EPOCH_TABLES, require_guards
from korpus.infrastructure.repository import SqlRepository
from korpus.infrastructure.schema import corpus_state_epoch
from korpus.infrastructure.semantic_release import semantic_release_members


class SqlCorpusSnapshotReader:
    """Capture semantic release identity and monotonic state without a long transaction."""

    def __init__(self, repository: SqlRepository) -> None:
        self.repository = repository
        self.engine = repository.engine
        setattr(repository, "corpus_snapshot_reader", self)

    def initialize(self, *, create_schema: bool) -> None:
        """Install guards for metadata-created dev schemas or verify migrated schemas."""
        with self.engine.begin() as connection:
            if create_schema:
                self._ensure_epoch_row(connection)
                self._install_guards(connection)
            self._require_epoch_row(connection)
            self._require_guards(connection)

    def capture(
        self,
        identity: Identity,
        corpus_ids: frozenset[str],
        as_of: date,
    ) -> CorpusReadToken:
        authorized = frozenset(corpus_ids.intersection(identity.corpora))
        with self.engine.begin() as connection:
            self.repository._apply_postgres_identity(connection, identity)
            before = self._epoch(connection)
            rows = []
            if authorized:
                statement = retrieval_queries.release_projection(identity, authorized, as_of)
                rows = connection.execute(statement).mappings().all()
            visible = [
                row for row in rows if retrieval_queries.release_row_is_current(row, as_of)
            ]
            unique = semantic_release_members(connection, visible)
            after = self._epoch(connection)
        if before != after:
            raise CorpusConsistencyError(
                "corpus state changed while release identity was captured"
            )

        return CorpusReadToken(
            state_epoch=before,
            release_id=release_identity_digest(unique),
            as_of=as_of,
            corpus_ids=authorized,
            authorization_scope_id=authorization_scope_id(identity, authorized),
        )

    def validate(
        self,
        identity: Identity,
        corpus_ids: frozenset[str],
        as_of: date,
        token: CorpusReadToken,
    ) -> None:
        authorized = frozenset(corpus_ids.intersection(identity.corpora))
        if token.as_of != as_of:
            raise CorpusConsistencyError("corpus token historical date does not match the read")
        if token.corpus_ids != authorized:
            raise CorpusConsistencyError("corpus token scope does not match the read")
        if token.authorization_scope_id != authorization_scope_id(identity, authorized):
            raise CorpusConsistencyError(
                "corpus token authorization identity does not match the read"
            )
        with self.engine.begin() as connection:
            self.repository._apply_postgres_identity(connection, identity)
            current = self._epoch(connection)
        if current != token.state_epoch:
            raise CorpusConsistencyError("corpus state changed after read token capture")

    @staticmethod
    def _epoch(connection: Connection) -> int:
        value = connection.execute(
            select(corpus_state_epoch.c.epoch).where(
                corpus_state_epoch.c.singleton_id == 1
            )
        ).scalar_one_or_none()
        if value is None:
            raise CorpusConsistencyError("corpus state epoch is not initialized")
        return int(value)

    @staticmethod
    def _ensure_epoch_row(connection: Connection) -> None:
        exists = connection.execute(
            select(corpus_state_epoch.c.singleton_id).where(
                corpus_state_epoch.c.singleton_id == 1
            )
        ).scalar_one_or_none()
        if exists is None:
            connection.execute(insert(corpus_state_epoch).values(singleton_id=1, epoch=0))

    @staticmethod
    def _require_epoch_row(connection: Connection) -> None:
        rows = connection.execute(select(corpus_state_epoch.c.singleton_id)).scalars().all()
        if rows != [1]:
            raise RuntimeError("corpus state epoch must contain exactly singleton row 1")

    def _install_guards(self, connection: Connection) -> None:
        dialect = connection.dialect.name
        if dialect == "sqlite":
            self._install_sqlite_guards(connection)
            return
        if dialect == "postgresql":
            self._install_postgres_guards(connection)
            return
        raise RuntimeError(f"unsupported corpus snapshot dialect: {dialect}")

    @staticmethod
    def _install_sqlite_guards(connection: Connection) -> None:
        for table in EPOCH_TABLES:
            for operation in ("INSERT", "UPDATE", "DELETE"):
                name = f"trg_{table}_epoch_{operation.lower()}"
                connection.execute(
                    sql_text(
                        f"CREATE TRIGGER IF NOT EXISTS {name} AFTER {operation} ON {table} BEGIN "
                        "UPDATE corpus_state_epoch SET epoch = epoch + 1 "
                        "WHERE singleton_id = 1; END"
                    )
                )
        connection.execute(
            sql_text(
                "CREATE TRIGGER IF NOT EXISTS trg_evidence_spans_immutable_insert "
                "BEFORE INSERT ON evidence_spans "
                "WHEN EXISTS (SELECT 1 FROM document_versions "
                "WHERE id = NEW.version_id AND evidence_digest IS NOT NULL) "
                "BEGIN SELECT RAISE(ABORT, 'sealed evidence is immutable'); END"
            )
        )
        connection.execute(
            sql_text(
                "CREATE TRIGGER IF NOT EXISTS trg_evidence_spans_immutable_delete "
                "BEFORE DELETE ON evidence_spans "
                "WHEN EXISTS (SELECT 1 FROM document_versions "
                "WHERE id = OLD.version_id AND evidence_digest IS NOT NULL) "
                "BEGIN SELECT RAISE(ABORT, 'sealed evidence is immutable'); END"
            )
        )
        connection.execute(
            sql_text(
                "CREATE TRIGGER IF NOT EXISTS trg_evidence_spans_immutable_update "
                "BEFORE UPDATE ON evidence_spans "
                "WHEN EXISTS (SELECT 1 FROM document_versions "
                "WHERE id IN (OLD.version_id, NEW.version_id) AND evidence_digest IS NOT NULL) "
                "BEGIN SELECT RAISE(ABORT, 'sealed evidence is immutable'); END"
            )
        )
        connection.execute(
            sql_text(
                "CREATE TRIGGER IF NOT EXISTS trg_approved_version_digest_immutable "
                "BEFORE UPDATE OF evidence_digest ON document_versions "
                "WHEN OLD.evidence_digest IS NOT NULL "
                "AND NEW.evidence_digest IS NOT OLD.evidence_digest "
                "BEGIN SELECT RAISE(ABORT, 'sealed evidence digest is immutable'); END"
            )
        )

    @staticmethod
    def _install_postgres_guards(connection: Connection) -> None:
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
            sql_text(
                "REVOKE ALL ON FUNCTION korpus_refuse_approved_evidence_mutation() FROM PUBLIC"
            )
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
                "DROP TRIGGER IF EXISTS trg_approved_version_digest_immutable "
                "ON document_versions"
            )
        )
        connection.execute(
            sql_text(
                "CREATE TRIGGER trg_approved_version_digest_immutable "
                "BEFORE UPDATE OF evidence_digest ON document_versions "
                "FOR EACH ROW EXECUTE FUNCTION korpus_refuse_approved_digest_mutation()"
            )
        )

    @staticmethod
    def _require_guards(connection: Connection) -> None:
        require_guards(connection)
