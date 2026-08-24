from datetime import date
from uuid import uuid4

import pytest
from korpus.application.retrieval import HybridLexicalRetriever, RetrievalWeights
from korpus.domain.models import (
    AccessTier,
    AuthorityClass,
    Classification,
    DocumentRecord,
    DocumentVersionRecord,
    EvidenceSpanRecord,
    Identity,
    ReviewState,
)
from korpus.infrastructure.semantic import HttpEmbeddingProvider, PgVectorSemanticIndex


def test_embedding_provider_configuration_is_fail_closed():
    with pytest.raises(ValueError):
        HttpEmbeddingProvider("http://remote.example/embed", "model", 384)
    with pytest.raises(ValueError):
        HttpEmbeddingProvider("https://embed.example", "bad model!", 384)


def test_pgvector_index_ddl_is_deterministic_partial_and_bounded():
    first = PgVectorSemanticIndex.index_ddl("ua-evidence-v1", 768, m=16, ef_construction=96)
    second = PgVectorSemanticIndex.index_ddl("ua-evidence-v1", 768, m=16, ef_construction=96)
    assert first == second
    assert "USING hnsw" in first
    assert "vector(768)" in first
    assert "WHERE model_id = 'ua-evidence-v1'" in first
    with pytest.raises(ValueError):
        PgVectorSemanticIndex.index_ddl("x", 9000)


def test_repository_protocol_can_materialize_authorized_semantic_ids(client):
    repository = client.app.state.repository
    result = repository.get_retrievable_spans_by_ids(
        client.identity_provider.current,
        frozenset({"public"}),
        date.today(),
        [uuid4()],
    )
    assert result == []


class FusionRepo:
    def __init__(self, lexical, semantic):
        self.lexical = lexical
        self.semantic = semantic

    def search_retrievable_spans(self, identity, corpus_ids, as_of, query, candidate_limit):
        return [self.lexical]

    def get_retrievable_spans_by_ids(self, identity, corpus_ids, as_of, span_ids):
        return [self.semantic] if self.semantic[0].id in span_ids else []


class SemanticSource:
    def __init__(self, span_id):
        self.span_id = span_id

    def search(self, identity, query, corpus_ids, as_of, limit):
        return [(self.span_id, 1.0)]


def _bundle(text, suffix):
    document = DocumentRecord(
        canonical_title=f"Doc {suffix}",
        corpus_id="public",
        issuer="Authority",
        jurisdiction="UA",
        document_type="order",
        access_tier=AccessTier.PUBLIC,
        classification=Classification.PUBLIC,
    )
    version = DocumentVersionRecord(
        document_id=document.id,
        revision="1",
        source_hash=suffix * 64,
        object_key=f"objects/{suffix}",
        mime_type="text/plain",
        authority=AuthorityClass.OFFICIAL_UA,
        review_state=ReviewState.APPROVED,
    )
    span = EvidenceSpanRecord(version_id=version.id, ordinal=0, text=text)
    return span, document, version


def test_semantic_candidates_are_authorized_materialized_and_fused():
    lexical = _bundle("lexical weather noise", "a")
    semantic = _bundle("authoritative evacuation procedure", "b")
    repo = FusionRepo(lexical, semantic)
    retriever = HybridLexicalRetriever(
        repo,
        candidate_budget=8,
        weights=RetrievalWeights(
            lexical=0.12,
            semantic=0.30,
            query_coverage=0.20,
            character=0.08,
            authority=0.18,
            phrase=0.08,
            temporal=0.04,
        ),
        semantic_source=SemanticSource(semantic[0].id),
    )
    identity = Identity(
        subject="u",
        roles=frozenset({"user"}),
        clearance=AccessTier.PUBLIC,
        corpora=frozenset({"public"}),
    )
    result = retriever.search(identity, "evacuation procedure", identity.corpora, date.today())
    assert any(item.span.id == semantic[0].id for item in result)


def test_postgres_rls_migration_is_default_deny_when_context_is_absent():
    migration_path = (
        __import__("pathlib").Path(__file__).parents[1]
        / "migrations/versions/0002_database_defense_and_vectors.py"
    )
    migration = migration_path.read_text()
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "current_setting('korpus.clearance', true)" in migration
    assert "COALESCE" in migration


class FailingSemanticSource:
    def search(self, identity, query, corpus_ids, as_of, limit):
        raise OSError("embedding gateway unavailable")


def test_required_semantic_failure_never_silently_falls_back_to_lexical():
    from korpus.application.retrieval import RetrievalUnavailable

    lexical = _bundle("evacuation procedure", "d")
    retriever = HybridLexicalRetriever(
        FusionRepo(lexical, lexical),
        candidate_budget=8,
        weights=RetrievalWeights(
            lexical=0.12,
            semantic=0.30,
            query_coverage=0.20,
            character=0.08,
            authority=0.18,
            phrase=0.08,
            temporal=0.04,
        ),
        semantic_source=FailingSemanticSource(),
    )
    identity = Identity(
        subject="u",
        roles=frozenset({"user"}),
        clearance=AccessTier.PUBLIC,
        corpora=frozenset({"public"}),
    )
    with pytest.raises(RetrievalUnavailable, match="semantic retrieval"):
        retriever.search(identity, "evacuation procedure", identity.corpora, date.today())
