"""Shared factories.

Every span is built explicitly so a test reads as a statement about the domain,
not as a struggle with constructors.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from korpus.domain.access import Principal
from korpus.domain.models import (
    AccessTier,
    AuthorityClass,
    Citation,
    EvidenceSpan,
    ReviewState,
)

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
# The corpus every fixture belongs to unless a test says otherwise, and the one every
# fixture principal is granted. Tests about scope override one side and not the other.
CORPUS = UUID("00000000-0000-4000-8000-000000000001")


def make_span(
    *,
    corpus_id: UUID | None = None,
    quote: str = "Пункт 4.2 визначає порядок дій.",
    text: str | None = None,
    score: float = 0.91,
    tier: AccessTier = AccessTier.PUBLIC,
    review: ReviewState = ReviewState.APPROVED,
    authority: AuthorityClass = AuthorityClass.OFFICIAL_UA,
    document_id: UUID | None = None,
    version_id: UUID | None = None,
    chunk_id: UUID | None = None,
    valid_until: datetime | None = None,
    superseded_by: UUID | None = None,
    title: str = "Настанова",
    page: int | None = 7,
) -> EvidenceSpan:
    document = document_id or uuid4()
    chunk = chunk_id or uuid4()
    return EvidenceSpan(
        citation=Citation(
            document_id=document,
            chunk_id=chunk,
            title=title,
            page=page,
            quote=quote,
        ),
        chunk_id=chunk,
        document_id=document,
        document_version_id=version_id or uuid4(),
        corpus_id=corpus_id or CORPUS,
        text=text if text is not None else quote,
        retrieval_score=score,
        access_tier=tier,
        review_state=review,
        authority=authority,
        valid_until=valid_until,
        superseded_by=superseded_by,
    )


def make_principal(
    tier: AccessTier = AccessTier.PUBLIC,
    corpora: frozenset[UUID] | None = None,
    subject_id: str = "soldier-1",
) -> Principal:
    return Principal(
        subject_id=subject_id,
        tier=tier,
        authorized_corpora=frozenset({CORPUS}) if corpora is None else corpora,
    )


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def client(tmp_path):  # type: ignore[no-untyped-def]
    """A client over a freshly wired app.

    The API holds process-local singletons on purpose (they are the seam where real
    adapters will be injected). Tests therefore rebuild them rather than inheriting
    another test's corpus — shared retrieval state between tests would make an
    access-control assertion depend on execution order.
    """
    from fastapi.testclient import TestClient
    from korpus.api import routes
    from korpus.config import Settings, get_settings
    from korpus.infrastructure.in_memory import StaticPrincipalResolver, SystemClock
    from korpus.infrastructure.resilience import CircuitBreaker, TokenBucket
    from korpus.main import create_app

    # Rebuilt exactly as the module wires it in production: an anonymous caller holds
    # the open corpus and nothing else. A fixture that granted more would test a
    # system nobody deploys.
    assert routes.OPEN_CORPUS == CORPUS
    routes._resolver = StaticPrincipalResolver(
        anonymous=Principal(
            subject_id="anonymous",
            tier=AccessTier.PUBLIC,
            authorized_corpora=frozenset({routes.OPEN_CORPUS}),
        )
    )
    routes._clock = SystemClock()
    # The breaker and the bucket are process-global by design; a test that inherited
    # another test's tripped circuit would fail for a reason that is not its own.
    routes._breaker = CircuitBreaker()
    routes._bucket = TokenBucket()
    get_settings.cache_clear()
    settings = Settings(
        environment="test",
        log_level="WARNING",
        llm_provider="stub",
        corpus_path=tmp_path / "korpus.sqlite3",
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client
    if routes._store is not None:
        routes._store.close()
    get_settings.cache_clear()
