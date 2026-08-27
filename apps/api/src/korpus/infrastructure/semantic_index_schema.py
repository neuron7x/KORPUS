"""Deterministic, injection-safe pgvector index schema generation."""

from __future__ import annotations

import hashlib
import re

MODEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")


def semantic_index_name(model_id: str, dimensions: int) -> str:
    if not MODEL_PATTERN.fullmatch(model_id) or not 8 <= dimensions <= 4000:
        raise ValueError("invalid model index parameters")
    suffix = hashlib.sha256(f"{model_id}:{dimensions}".encode()).hexdigest()[:12]
    return f"ix_span_embedding_hnsw_{suffix}"


def semantic_index_ddl(
    model_id: str, dimensions: int, *, m: int = 16, ef_construction: int = 64
) -> str:
    name = semantic_index_name(model_id, dimensions)
    if not 4 <= m <= 64 or not 16 <= ef_construction <= 1000:
        raise ValueError("invalid HNSW parameters")
    escaped_model = model_id.replace("'", "''")
    return (
        f"CREATE INDEX IF NOT EXISTS {name} ON span_embeddings USING hnsw "
        f"((embedding_vector::vector({dimensions})) vector_cosine_ops) "
        f"WITH (m = {m}, ef_construction = {ef_construction}) "
        f"WHERE model_id = '{escaped_model}' AND dimensions = {dimensions};"
    )
