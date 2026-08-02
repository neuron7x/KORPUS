"""Claim-level verification in isolation."""

import pytest
from conftest import make_principal, make_span

from korpus.application.verification import verify
from korpus.domain.models import AccessTier, Claim


def test_no_claims_is_zero_coverage_and_flagged_empty() -> None:
    result = verify([], [], [], make_principal())
    assert result.coverage == 0.0
    assert result.empty is True
    assert result.integrity_breach is False


def test_fully_cited_claims_reach_full_coverage() -> None:
    span = make_span()
    result = verify(
        [Claim(text="a", citation_indexes=(0,))],
        [span.citation],
        [span],
        make_principal(),
    )
    assert result.coverage == 1.0
    assert result.unsupported == ()


def test_uncited_claim_lowers_coverage() -> None:
    span = make_span()
    result = verify(
        [Claim(text="a", citation_indexes=(0,)), Claim(text="b")],
        [span.citation],
        [span],
        make_principal(),
    )
    assert result.coverage == pytest.approx(0.5)
    assert result.unsupported == (1,)


def test_out_of_range_index_is_an_integrity_breach() -> None:
    span = make_span()
    result = verify(
        [Claim(text="a", citation_indexes=(3,))], [span.citation], [span], make_principal()
    )
    assert result.integrity_breach is True
    assert result.coverage == 0.0


def test_citing_evidence_above_the_reader_tier_is_an_integrity_breach() -> None:
    span = make_span(tier=AccessTier.RESTRICTED)
    result = verify(
        [Claim(text="a", citation_indexes=(0,))],
        [span.citation],
        [span],
        make_principal(tier=AccessTier.PUBLIC),
    )
    assert result.integrity_breach is True
    assert result.unauthorized == (0,)


def test_a_claim_citing_two_sources_counts_once() -> None:
    first, second = make_span(), make_span()
    result = verify(
        [Claim(text="a", citation_indexes=(0, 1))],
        [first.citation, second.citation],
        [first, second],
        make_principal(),
    )
    assert result.coverage == 1.0


def test_mixed_valid_and_invalid_indexes_do_not_support_a_claim() -> None:
    span = make_span()
    result = verify(
        [Claim(text="a", citation_indexes=(0, 9))],
        [span.citation],
        [span],
        make_principal(),
    )
    assert result.coverage == 0.0
    assert result.integrity_breach is True


def test_limitations_are_populated_for_a_human_reader() -> None:
    span = make_span()
    result = verify([Claim(text="a")], [span.citation], [span], make_principal())
    assert result.limitations
    assert any("без підтвердженого джерела" in text for text in result.limitations)
