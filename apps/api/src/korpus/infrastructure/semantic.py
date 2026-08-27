from __future__ import annotations

import json
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import Engine
from sqlalchemy import text as sql_text

from korpus.domain.models import Identity
from korpus.infrastructure.embedding_provider import EmbeddingProvider
from korpus.infrastructure.embedding_provider import HttpEmbeddingProvider as HttpEmbeddingProvider
from korpus.infrastructure.semantic_coverage import SemanticCoverageReader
from korpus.infrastructure.semantic_index_schema import semantic_index_ddl, semantic_index_name
from korpus.security.corpus_governance import CorpusGovernanceProfile


class PgVectorSemanticIndex(SemanticCoverageReader):
    """Authorized pgvector candidate source with RLS as an independent barrier."""

    def __init__(
        self,
        engine: Engine,
        provider: EmbeddingProvider,
        *,
        corpus_governance: CorpusGovernanceProfile | None = None,
    ) -> None:
        if engine.dialect.name != "postgresql":
            raise ValueError("pgvector integration requires PostgreSQL")
        self.engine = engine
        self.provider = provider
        self.corpus_governance = corpus_governance

    def search(
        self,
        identity: Identity,
        query: str,
        corpus_ids: frozenset[str],
        as_of: date,
        limit: int,
    ) -> list[tuple[UUID, float]]:
        from korpus.infrastructure.repository import SqlRepository

        authorized = corpus_ids.intersection(identity.corpora)
        if not authorized or limit < 1:
            return []
        if self.corpus_governance is not None:
            self.corpus_governance.require_external_embedding(frozenset(authorized))
        vector = self.provider.embed(query)
        vector_literal = "[" + ",".join(f"{value:.9g}" for value in vector) + "]"
        statement = sql_text(
            """
            SELECT s.id AS span_id,
                   GREATEST(0.0, LEAST(1.0, 1.0 - (e.embedding_vector <=> \
CAST(:vector AS vector)))) AS score
            FROM span_embeddings e
            JOIN evidence_spans s ON s.id = e.span_id
            JOIN document_versions v ON v.id = s.version_id
            JOIN documents d ON d.id = v.document_id
            WHERE e.model_id = :model_id
              AND e.dimensions = :dimensions
              AND e.text_hash = s.text_hash
              AND v.review_state = 'approved'
              AND d.corpus_id = ANY(CAST(:corpora AS text[]))
              AND d.access_tier <= :clearance
              AND d.classification = ANY(CAST(:classifications AS text[]))
              AND (v.effective_from IS NULL OR v.effective_from <= :as_of)
              AND (v.effective_until IS NULL OR v.effective_until >= :as_of)
              AND (v.rescinded_at IS NULL OR CAST(v.rescinded_at AS date) > :as_of)
            ORDER BY e.embedding_vector <=> CAST(:vector AS vector), s.id
            LIMIT :limit
            """
        )
        classifications = SqlRepository._allowed_classifications(identity.clearance)
        with self.engine.begin() as connection:
            SqlRepository._apply_postgres_identity(connection, identity)
            rows = connection.execute(
                statement,
                {
                    "vector": vector_literal,
                    "model_id": self.provider.model_id,
                    "dimensions": self.provider.dimensions,
                    "corpora": list(sorted(authorized)),
                    "clearance": int(identity.clearance),
                    "classifications": classifications,
                    "as_of": as_of,
                    "limit": limit,
                },
            ).all()
        return [(UUID(row.span_id), float(row.score)) for row in rows]

    def upsert(self, identity: Identity, span_id: UUID, text: str, text_hash: str) -> None:
        from korpus.infrastructure.repository import SqlRepository

        with self.engine.begin() as connection:
            SqlRepository._apply_postgres_identity(connection, identity)
            corpus_row = connection.execute(
                sql_text(
                    """
                    SELECT d.corpus_id
                    FROM evidence_spans s
                    JOIN document_versions v ON v.id = s.version_id
                    JOIN documents d ON d.id = v.document_id
                    WHERE s.id = :span_id
                    """
                ),
                {"span_id": str(span_id)},
            ).first()
        if corpus_row is None:
            raise PermissionError("embedding target is not visible to the identity")
        if self.corpus_governance is not None:
            self.corpus_governance.require_external_embedding(
                frozenset({str(corpus_row.corpus_id)})
            )
        vector = self.provider.embed(text)
        vector_literal = "[" + ",".join(f"{value:.9g}" for value in vector) + "]"
        with self.engine.begin() as connection:
            SqlRepository._apply_postgres_identity(connection, identity)
            connection.execute(
                sql_text(
                    """
                    INSERT INTO span_embeddings(
                        span_id, model_id, dimensions, embedding_json, embedding_vector, \
text_hash, created_at
                    ) VALUES (
                        :span_id, :model_id, :dimensions, :embedding_json,
                        CAST(:vector AS vector), :text_hash, :created_at
                    )
                    ON CONFLICT(span_id, model_id) DO UPDATE SET
                        dimensions = excluded.dimensions,
                        embedding_json = excluded.embedding_json,
                        embedding_vector = excluded.embedding_vector,
                        text_hash = excluded.text_hash,
                        created_at = excluded.created_at
                    """
                ),
                {
                    "span_id": str(span_id),
                    "model_id": self.provider.model_id,
                    "dimensions": self.provider.dimensions,
                    "embedding_json": json.dumps(vector, separators=(",", ":")),
                    "vector": vector_literal,
                    "text_hash": text_hash,
                    "created_at": datetime.now(UTC),
                },
            )

    def healthcheck(self) -> bool:
        return self.provider.healthcheck()

    def close(self) -> None:
        self.provider.close()

    @staticmethod
    def index_name(model_id: str, dimensions: int) -> str:
        return semantic_index_name(model_id, dimensions)

    def ensure_index(self, *, m: int = 16, ef_construction: int = 64) -> str:
        ddl = self.index_ddl(
            self.provider.model_id, self.provider.dimensions, m=m, ef_construction=ef_construction
        )
        with self.engine.begin() as connection:
            connection.exec_driver_sql(ddl)
        return self.index_name(self.provider.model_id, self.provider.dimensions)

    @staticmethod
    def index_ddl(
        model_id: str,
        dimensions: int,
        *,
        m: int = 16,
        ef_construction: int = 64,
    ) -> str:
        return semantic_index_ddl(model_id, dimensions, m=m, ef_construction=ef_construction)
