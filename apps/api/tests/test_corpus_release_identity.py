"""The release id names the versions an answer could be drawn from, and costs one query.

`corpus_release_id` read the full span projection and built a span, a document and a
version model for every row. On the imported corpus — 116 229 spans over 1616 versions —
that was 232 458 Pydantic constructions per question: 6.9 s of a 17 s answer, while the
retrieval it stamps has a 1200 ms budget. Nothing about the answer was wrong; it simply
took long enough that the system was unusable, and the reader had no way to tell a slow
corpus from a broken one.

The digest never used anything but four strings per version. It is computed from the
versions now, joined through `evidence_spans` so "has at least one retrievable span"
still decides membership. Measured 2026-08-06: same digest, 6888 ms → 49 ms.

The first test is the one that matters: the new value must equal the old *definition*,
computed here from the span projection. Speed is not asserted — that measures the
machine — but equivalence is, because a release id that changed meaning would silently
re-stamp every answer this corpus has already given.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

from fastapi.testclient import TestClient
from korpus.domain.models import AccessTier, Identity

from apps.api.tests.helpers import approve, ingest_text

READER = Identity(
    subject="reader",
    roles=frozenset({"user"}),
    clearance=AccessTier.PUBLIC,
    corpora=frozenset({"public"}),
)


def _repository(client: TestClient) -> object:
    """The live repository behind the running app — there is no fixture for it."""
    return client.app.state.repository


def _digest_from_spans(repository: object, as_of: date) -> str:
    """The definition this replaced, kept here as the thing to agree with."""
    rows = repository.list_retrievable_spans(  # type: ignore[attr-defined]
        READER, frozenset({"public"}), as_of
    )
    unique = {
        (str(document.id), str(version.id), version.source_hash, version.review_state.value)
        for _, document, version in rows
    }
    digest = hashlib.sha256()
    for row in sorted(unique):
        digest.update(":".join(row).encode("utf-8") + b"\n")
    return digest.hexdigest()[:16]


def test_the_release_id_equals_the_definition_it_replaced(
    client: TestClient
) -> None:
    repository = _repository(client)
    for index in range(3):
        result = ingest_text(
            client,
            title=f"Наказ {index}",
            text=f"Підрозділ веде журнал {index}. Кожен запис має дату та відповідальну особу.",
        )
        approve(client, result["version"]["id"])
    as_of = date.today()

    computed = repository.corpus_release_id(  # type: ignore[attr-defined]
        READER, frozenset({"public"}), as_of
    )

    assert computed == _digest_from_spans(repository, as_of)


def test_a_version_that_changes_changes_the_release_id(
    client: TestClient
) -> None:
    """The negative control: a digest that never moves identifies nothing."""
    repository = _repository(client)
    as_of = date.today()
    before = repository.corpus_release_id(  # type: ignore[attr-defined]
        READER, frozenset({"public"}), as_of
    )

    result = ingest_text(client, title="Новий наказ", text="Новий порядок обліку майна.")
    approve(client, result["version"]["id"])

    after = repository.corpus_release_id(  # type: ignore[attr-defined]
        READER, frozenset({"public"}), as_of
    )
    assert after != before


def test_a_quarantined_version_is_not_in_the_release(
    client: TestClient
) -> None:
    """Membership is "could an answer cite it", not "is it in the database"."""
    repository = _repository(client)
    as_of = date.today()
    before = repository.corpus_release_id(  # type: ignore[attr-defined]
        READER, frozenset({"public"}), as_of
    )

    ingest_text(client, title="Непереглянутий", text="Текст, який ніхто не затверджував.")

    after = repository.corpus_release_id(  # type: ignore[attr-defined]
        READER, frozenset({"public"}), as_of
    )
    assert after == before


def test_a_corpus_the_reader_cannot_reach_yields_the_empty_digest(
    client: TestClient,
) -> None:
    repository = _repository(client)
    outsider = Identity(
        subject="outsider",
        roles=frozenset({"user"}),
        clearance=AccessTier.PUBLIC,
        corpora=frozenset({"other"}),
    )

    computed = repository.corpus_release_id(  # type: ignore[attr-defined]
        outsider, frozenset({"other"}), date.today()
    )

    assert computed == hashlib.sha256().hexdigest()[:16]


def test_a_version_not_yet_in_force_is_not_in_the_release(client: TestClient) -> None:
    """The release names what could be cited *on the date asked*, not what exists.

    The currency rule used to come free: the old path built a version model for every
    span and called `is_valid_on`. Computing the digest from a projection means asking
    the same question explicitly, and forgetting to would put tomorrow's order into
    today's fingerprint.
    """
    repository = _repository(client)
    as_of = date.today()
    before = repository.corpus_release_id(  # type: ignore[attr-defined]
        READER, frozenset({"public"}), as_of
    )

    result = ingest_text(
        client,
        title="Наказ, що набирає сили пізніше",
        text="Порядок, який починає діяти наступного місяця.",
        publication_date=None,
        effective_from=as_of + timedelta(days=30),
    )
    approve(client, result["version"]["id"])

    after = repository.corpus_release_id(  # type: ignore[attr-defined]
        READER, frozenset({"public"}), as_of
    )
    assert after == before, "a version that governs nothing today entered today's release"

    later = repository.corpus_release_id(  # type: ignore[attr-defined]
        READER, frozenset({"public"}), as_of + timedelta(days=31)
    )
    assert later != before, "and it must enter the release for a date it does govern"
