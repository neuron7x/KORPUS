"""Resumable, database-checkpointed embedding backfill for PostgreSQL."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Engine
from sqlalchemy import text as sql_text

from korpus.domain.models import Identity
from korpus.infrastructure.embedding_provider import EmbeddingProvider
from korpus.infrastructure.resource_contracts import count
from korpus.security.corpus_governance import CorpusGovernanceProfile


@dataclass(frozen=True)
class BackfillResult:
    selected: int
    written: int
    stale_during_write: int
    complete: bool


class PgVectorEmbeddingBackfill:
    """Build one bounded batch; persisted vectors are the durable resume checkpoint."""

    def __init__(
        self,
        engine: Engine,
        provider: EmbeddingProvider,
        *,
        batch_size: int = 32,
        corpus_governance: CorpusGovernanceProfile | None = None,
    ) -> None:
        if engine.dialect.name != "postgresql":
            raise ValueError("embedding backfill requires PostgreSQL")
        self.engine = engine
        self.provider = provider
        self.batch_size = count(batch_size, 1, "batch_size")
        if self.batch_size > 64:
            raise ValueError("batch_size must not exceed 64")
        self.corpus_governance = corpus_governance

    def run_batch(self, identity: Identity) -> BackfillResult:
        from korpus.infrastructure.repository import SqlRepository

        with self.engine.begin() as connection:
            SqlRepository._apply_postgres_identity(connection, identity)
            rows = connection.execute(
                sql_text(
                    """
                    SELECT s.id, s.text, s.text_hash, d.corpus_id
                    FROM evidence_spans s
                    JOIN document_versions v ON v.id = s.version_id
                    JOIN documents d ON d.id = v.document_id
                    LEFT JOIN span_embeddings e
                      ON e.span_id = s.id AND e.model_id = :model_id
                    WHERE v.review_state = 'approved'
                      AND (e.span_id IS NULL OR e.dimensions <> :dimensions
                           OR e.text_hash <> s.text_hash)
                    ORDER BY s.id
                    LIMIT :batch_size
                    """
                ),
                {
                    "model_id": self.provider.model_id,
                    "dimensions": self.provider.dimensions,
                    "batch_size": self.batch_size,
                },
            ).all()
        if not rows:
            return BackfillResult(0, 0, 0, True)
        corpora = frozenset(str(row.corpus_id) for row in rows)
        if self.corpus_governance is not None:
            self.corpus_governance.require_external_embedding(corpora)
        vectors = self.provider.embed_many([str(row.text) for row in rows])
        written = 0
        with self.engine.begin() as connection:
            SqlRepository._apply_postgres_identity(connection, identity)
            for row, vector in zip(rows, vectors, strict=True):
                literal = "[" + ",".join(f"{value:.9g}" for value in vector) + "]"
                result = connection.execute(
                    sql_text(
                        """
                        INSERT INTO span_embeddings(
                            span_id, model_id, dimensions, embedding_json,
                            embedding_vector, text_hash, created_at
                        )
                        SELECT s.id, :model_id, :dimensions, :embedding_json,
                               CAST(:vector AS vector), CAST(:text_hash AS varchar(64)),
                               :created_at
                        FROM evidence_spans s
                        WHERE s.id = :span_id
                          AND s.text_hash = CAST(:text_hash AS varchar(64))
                        ON CONFLICT(span_id, model_id) DO UPDATE SET
                            dimensions = excluded.dimensions,
                            embedding_json = excluded.embedding_json,
                            embedding_vector = excluded.embedding_vector,
                            text_hash = excluded.text_hash,
                            created_at = excluded.created_at
                        """
                    ),
                    {
                        "span_id": str(row.id),
                        "model_id": self.provider.model_id,
                        "dimensions": self.provider.dimensions,
                        "embedding_json": json.dumps(vector, separators=(",", ":")),
                        "vector": literal,
                        "text_hash": str(row.text_hash),
                        "created_at": datetime.now(UTC),
                    },
                )
                written += max(0, int(result.rowcount))
        return BackfillResult(len(rows), written, len(rows) - written, False)
