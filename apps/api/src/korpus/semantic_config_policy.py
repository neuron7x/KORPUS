"""Fail-closed cross-field policy for external semantic retrieval."""

from __future__ import annotations

from typing import Any

from korpus.security.url_policy import is_https_url


def validate_semantic_retrieval(settings: Any, *, controlled: bool) -> None:
    if not settings.semantic_retrieval_enabled:
        if settings.semantic_weight != 0:
            raise ValueError("semantic weight must be zero when semantic retrieval is disabled")
        return
    if not settings.database_url.startswith("postgresql"):
        raise ValueError("semantic retrieval requires PostgreSQL/pgvector")
    if not settings.embedding_endpoint or not settings.embedding_model_id:
        raise ValueError("semantic retrieval requires embedding endpoint and model id")
    if settings.semantic_weight <= 0 and settings.answer_policy_mode == "development":
        raise ValueError("semantic retrieval requires a positive semantic weight")
    if controlled and not is_https_url(settings.embedding_endpoint):
        raise ValueError("controlled embedding endpoints must use HTTPS")
    if controlled and not settings.resolved_embedding_token:
        raise ValueError("controlled embedding integration requires authentication")
    if not settings.corpus_governance_profile_path or not settings.corpus_governance_profile_sha256:
        raise ValueError("semantic retrieval requires a digest-bound corpus governance profile")
