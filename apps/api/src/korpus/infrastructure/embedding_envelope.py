from __future__ import annotations

from typing import Any


def embedding_vector(payload: Any) -> object:
    """Read exactly one vector from a bounded custom, Ollama or OpenAI envelope."""
    if not isinstance(payload, dict):
        return None
    if "embedding" in payload:
        return payload["embedding"]
    embeddings = payload.get("embeddings")
    if isinstance(embeddings, list) and len(embeddings) == 1:
        return embeddings[0]
    data = payload.get("data")
    if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
        return data[0].get("embedding")
    return None
