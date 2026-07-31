from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol
from uuid import UUID

import httpx
from sqlalchemy import Engine, text as sql_text

from korpus.domain.models import Identity

MODEL_PATTERN = re.compile(r"^[A-Za-z0-9._:/-]{1,200}$")


class EmbeddingProvider(Protocol):
    model_id: str
    dimensions: int

    def embed(self, text: str) -> list[float]: ...


@dataclass(frozen=True)
class HttpEmbeddingProvider:
    """Vendor-neutral internal embedding service integration."""

    endpoint: str
    model_id: str
    dimensions: int
    token: str | None = None
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not self.endpoint.startswith(("https://", "http://127.0.0.1", "http://localhost")):
            raise ValueError("embedding endpoint must use HTTPS or loopback HTTP")
        if not MODEL_PATTERN.fullmatch(self.model_id) or self.dimensions < 8:
            raise ValueError("invalid embedding model configuration")

    def embed(self, text: str) -> list[float]:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        response = httpx.post(
            self.endpoint,
            json={"model": self.model_id, "input": text},
            headers=headers,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        vector = payload.get("embedding")
        if not isinstance(vector, list) or len(vector) != self.dimensions:
            raise RuntimeError("embedding service returned invalid dimensions")
        values = [float(value) for value in vector]
        norm = sum(value * value for value in values) ** 0.5
        if norm == 0 or any(not (-1e6 < value < 1e6) for value in values):
            raise RuntimeError("embedding service returned invalid vector")
        return [value / norm for value in values]


class PgVectorSemanticIndex:
    """Authorized pgvector candidate source.

    Authorization predicates are repeated in SQL and PostgreSQL RLS is expected
    as a second independent barrier. Returned similarity is normalized cosine
    similarity in [0, 1].
    """

    def __init__(self, engine: Engine, provider: EmbeddingProvider) -> None:
        if engine.dialect.name != "postgresql":
            raise ValueError("pgvector integration requires PostgreSQL")
        self.engine = engine
        self.provider = provider

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
        vector = self.provider.embed(query)
        vector_literal = "[" + ",".join(f"{value:.9g}" for value in vector) + "]"
        statement = sql_text(
            """
            SELECT s.id AS span_id,
                   GREATEST(0.0, LEAST(1.0, 1.0 - (e.embedding_vector <=> CAST(:vector AS vector)))) AS score
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
            )
        return [(UUID(row.span_id), float(row.score)) for row in rows]

    def upsert(self, span_id: UUID, text: str, text_hash: str) -> None:
        vector = self.provider.embed(text)
        vector_literal = "[" + ",".join(f"{value:.9g}" for value in vector) + "]"
        with self.engine.begin() as connection:
            connection.execute(
                sql_text(
                    """
                    INSERT INTO span_embeddings(
                        span_id, model_id, dimensions, embedding_json, embedding_vector, text_hash, created_at
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

    @staticmethod
    def index_ddl(model_id: str, dimensions: int, *, m: int = 16, ef_construction: int = 64) -> str:
        if not MODEL_PATTERN.fullmatch(model_id) or not 8 <= dimensions <= 4000:
            raise ValueError("invalid model index parameters")
        if not 4 <= m <= 64 or not 16 <= ef_construction <= 1000:
            raise ValueError("invalid HNSW parameters")
        suffix = hashlib.sha256(f"{model_id}:{dimensions}".encode()).hexdigest()[:12]
        escaped_model = model_id.replace("'", "''")
        return (
            f"CREATE INDEX IF NOT EXISTS ix_span_embedding_hnsw_{suffix} "
            f"ON span_embeddings USING hnsw ((embedding_vector::vector({dimensions})) vector_cosine_ops) "
            f"WITH (m = {m}, ef_construction = {ef_construction}) "
            f"WHERE model_id = '{escaped_model}' AND dimensions = {dimensions};"
        )
