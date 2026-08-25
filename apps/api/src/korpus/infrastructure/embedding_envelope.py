from __future__ import annotations

from typing import Any


def embedding_vectors(payload: Any) -> list[object] | None:
    """Read an ordered vector batch from a bounded custom, Ollama or OpenAI envelope."""
    if not isinstance(payload, dict):
        return None
    if "embedding" in payload:
        return [payload["embedding"]]
    embeddings = payload.get("embeddings")
    if isinstance(embeddings, list):
        return embeddings
    data = payload.get("data")
    if isinstance(data, list) and all(isinstance(item, dict) for item in data):
        return [item.get("embedding") for item in data]
    return None
