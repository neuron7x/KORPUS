"""Deployment admission projection for required semantic retrieval."""

from __future__ import annotations

from typing import Any

from korpus.application.embedding_coverage import EmbeddingCoverage, semantic_retrieval_admissible
from korpus.domain.models import AccessTier, Identity


def semantic_status(enabled: bool, source: Any | None) -> tuple[bool, EmbeddingCoverage | None]:
    if not enabled:
        return True, None
    if source is None or source.corpus_governance is None:
        return False, None
    corpora = frozenset(source.corpus_governance.corpora)
    identity = Identity(
        subject="semantic-readiness",
        roles=frozenset({"admin"}),
        clearance=AccessTier.RESTRICTED,
        corpora=corpora,
    )
    coverage = source.coverage(identity, corpora)
    admitted, _ = semantic_retrieval_admissible(coverage)
    return admitted, coverage


def failure_reason(*, object_store: bool, schema: bool, semantic: bool) -> str:
    if not object_store:
        return "object_store"
    if not schema:
        return "schema"
    return "semantic_index" if not semantic else "audit_backlog"
