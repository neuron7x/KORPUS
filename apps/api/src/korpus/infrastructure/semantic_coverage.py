"""PostgreSQL measurement adapter for model/hash/dimension embedding coverage."""

from __future__ import annotations

from sqlalchemy import Engine
from sqlalchemy import text as sql_text

from korpus.application.embedding_coverage import EmbeddingCoverage, assess_embedding_coverage
from korpus.domain.models import Identity
from korpus.infrastructure.embedding_provider import EmbeddingProvider


class SemanticCoverageReader:
    engine: Engine
    provider: EmbeddingProvider

    def coverage(self, identity: Identity, corpus_ids: frozenset[str]) -> EmbeddingCoverage:
        from korpus.infrastructure.repository import SqlRepository

        authorized = corpus_ids.intersection(identity.corpora)
        if not authorized:
            return assess_embedding_coverage(
                active_model_id=self.provider.model_id,
                active_dimensions=self.provider.dimensions,
                spans_total=0,
                spans_embedded_active=0,
                spans_embedded_other_model=0,
                spans_stale_text=0,
            )
        with self.engine.begin() as connection:
            SqlRepository._apply_postgres_identity(connection, identity)  # noqa: SLF001
            row = connection.execute(
                sql_text(
                    """
                    SELECT COUNT(*) AS spans_total,
                      COUNT(*) FILTER (WHERE EXISTS (
                        SELECT 1 FROM span_embeddings e WHERE e.span_id = s.id
                          AND e.model_id = :model_id AND e.dimensions = :dimensions
                          AND e.text_hash = s.text_hash
                      )) AS spans_embedded_active,
                      COUNT(*) FILTER (WHERE EXISTS (
                        SELECT 1 FROM span_embeddings e WHERE e.span_id = s.id
                          AND e.model_id <> :model_id
                      )) AS spans_embedded_other_model,
                      COUNT(*) FILTER (WHERE EXISTS (
                        SELECT 1 FROM span_embeddings e WHERE e.span_id = s.id
                          AND e.model_id = :model_id AND e.text_hash <> s.text_hash
                      )) AS spans_stale_text
                    FROM evidence_spans s
                    JOIN document_versions v ON v.id = s.version_id
                    JOIN documents d ON d.id = v.document_id
                    WHERE v.review_state = 'approved'
                      AND d.corpus_id = ANY(CAST(:corpora AS text[]))
                    """
                ),
                {
                    "model_id": self.provider.model_id,
                    "dimensions": self.provider.dimensions,
                    "corpora": sorted(authorized),
                },
            ).one()
        return assess_embedding_coverage(
            active_model_id=self.provider.model_id,
            active_dimensions=self.provider.dimensions,
            spans_total=int(row.spans_total),
            spans_embedded_active=int(row.spans_embedded_active),
            spans_embedded_other_model=int(row.spans_embedded_other_model),
            spans_stale_text=int(row.spans_stale_text),
        )
