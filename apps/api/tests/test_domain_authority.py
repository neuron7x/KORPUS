"""Authority precedence, validity, supersession, conflict exposure."""

from datetime import timedelta
from uuid import uuid4

from conftest import NOW, make_span

from korpus.domain.authority import (
    AUTHORITY_RANK,
    conflicting_versions,
    deduplicate_by_version,
    is_current,
    may_govern,
    order_by_precedence,
    precedence_key,
)
from korpus.domain.models import AuthorityClass


def test_every_authority_class_is_ranked() -> None:
    assert set(AUTHORITY_RANK) == set(AuthorityClass)


def test_official_ua_outranks_every_other_class() -> None:
    official = AUTHORITY_RANK[AuthorityClass.OFFICIAL_UA]
    assert all(
        official < rank
        for cls, rank in AUTHORITY_RANK.items()
        if cls is not AuthorityClass.OFFICIAL_UA
    )


def test_adversary_material_may_never_govern() -> None:
    assert may_govern(make_span(authority=AuthorityClass.ADVERSARY)) is False


def test_unknown_authority_may_never_govern() -> None:
    assert may_govern(make_span(authority=AuthorityClass.UNKNOWN)) is False


def test_official_material_may_govern() -> None:
    assert may_govern(make_span(authority=AuthorityClass.OFFICIAL_UA)) is True


def test_superseded_span_is_not_current() -> None:
    assert is_current(make_span(superseded_by=uuid4()), NOW) is False


def test_expired_span_is_not_current() -> None:
    assert is_current(make_span(valid_until=NOW - timedelta(seconds=1)), NOW) is False


def test_span_expiring_exactly_now_is_not_current() -> None:
    """The boundary is closed against the stale document, not against the reader."""
    assert is_current(make_span(valid_until=NOW), NOW) is False


def test_span_valid_in_the_future_is_current() -> None:
    assert is_current(make_span(valid_until=NOW + timedelta(days=1)), NOW) is True


def test_span_without_validity_window_is_current() -> None:
    assert is_current(make_span(), NOW) is True


def test_authority_outranks_retrieval_score() -> None:
    weak_official = make_span(score=0.75, authority=AuthorityClass.OFFICIAL_UA)
    strong_analytical = make_span(score=1.0, authority=AuthorityClass.ANALYTICAL)
    ordered = order_by_precedence([strong_analytical, weak_official])
    assert ordered[0] is weak_official


def test_score_breaks_ties_within_one_authority_class() -> None:
    low = make_span(score=0.80)
    high = make_span(score=0.95)
    assert order_by_precedence([low, high])[0] is high


def test_precedence_key_is_deterministic_for_equal_rank_and_score() -> None:
    first = make_span(score=0.9, chunk_id=uuid4())
    second = make_span(score=0.9, chunk_id=uuid4())
    ordered = [order_by_precedence([first, second]), order_by_precedence([second, first])]
    assert ordered[0] == ordered[1]
    assert precedence_key(first)[:2] == precedence_key(second)[:2]


def test_two_chunks_of_one_version_collapse_to_one() -> None:
    version = uuid4()
    best = make_span(score=0.95, version_id=version)
    worse = make_span(score=0.80, version_id=version)
    kept = deduplicate_by_version([worse, best])
    assert len(kept) == 1
    assert kept[0].retrieval_score == 0.95


def test_distinct_versions_are_both_kept() -> None:
    assert len(deduplicate_by_version([make_span(), make_span()])) == 2


def test_conflict_between_equal_authority_documents_is_exposed() -> None:
    first = make_span(authority=AuthorityClass.OFFICIAL_UA)
    second = make_span(authority=AuthorityClass.OFFICIAL_UA)
    assert len(conflicting_versions([first, second])) == 2


def test_no_conflict_when_one_document_dominates() -> None:
    document = uuid4()
    first = make_span(document_id=document, authority=AuthorityClass.OFFICIAL_UA)
    second = make_span(document_id=document, authority=AuthorityClass.OFFICIAL_UA)
    assert conflicting_versions([first, second]) == ()


def test_no_conflict_between_different_authority_levels() -> None:
    top = make_span(authority=AuthorityClass.OFFICIAL_UA)
    lower = make_span(authority=AuthorityClass.ANALYTICAL)
    assert conflicting_versions([top, lower]) == ()


def test_conflicts_of_empty_set_is_empty() -> None:
    assert conflicting_versions([]) == ()
