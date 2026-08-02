"""Access decisions (ADR-0004). These tests are the reason the module exists."""

from uuid import uuid4

from conftest import make_principal, make_span
from korpus.domain.access import (
    TIER_ORDER,
    DenialReason,
    allowed_tiers,
    authorize,
    readable,
)
from korpus.domain.models import AccessTier


def test_tier_order_is_a_strict_total_order() -> None:
    ranks = [TIER_ORDER[tier] for tier in AccessTier]
    assert sorted(ranks) == list(range(len(AccessTier)))
    assert TIER_ORDER[AccessTier.PUBLIC] < TIER_ORDER[AccessTier.AUTHENTICATED]
    assert TIER_ORDER[AccessTier.AUTHENTICATED] < TIER_ORDER[AccessTier.REVIEWED]
    assert TIER_ORDER[AccessTier.REVIEWED] < TIER_ORDER[AccessTier.RESTRICTED]


def test_public_principal_sees_only_public() -> None:
    assert allowed_tiers(AccessTier.PUBLIC) == frozenset({AccessTier.PUBLIC})


def test_restricted_principal_sees_every_tier() -> None:
    assert allowed_tiers(AccessTier.RESTRICTED) == frozenset(AccessTier)


def test_reviewed_principal_does_not_see_restricted() -> None:
    tiers = allowed_tiers(AccessTier.REVIEWED)
    assert AccessTier.RESTRICTED not in tiers
    assert AccessTier.REVIEWED in tiers


def test_requesting_an_unheld_corpus_is_denied() -> None:
    wanted = uuid4()
    decision = authorize(make_principal(), [wanted])
    assert decision.allowed is False
    assert decision.reason is DenialReason.CORPUS_NOT_AUTHORIZED
    assert decision.denied_corpora == (wanted,)


def test_requesting_a_held_corpus_is_allowed() -> None:
    held = uuid4()
    decision = authorize(make_principal(corpora=frozenset({held})), [held])
    assert decision.allowed is True
    assert decision.denied_corpora == ()


def test_partial_authorization_denies_the_whole_request() -> None:
    held, missing = uuid4(), uuid4()
    decision = authorize(make_principal(corpora=frozenset({held})), [held, missing])
    assert decision.allowed is False
    assert decision.denied_corpora == (missing,)


def test_no_requested_corpus_is_not_a_denial() -> None:
    assert authorize(make_principal(), []).allowed is True


def test_readable_rejects_span_above_principal_tier() -> None:
    span = make_span(tier=AccessTier.RESTRICTED)
    assert readable(span, make_principal(tier=AccessTier.REVIEWED)) is False


def test_readable_accepts_span_at_and_below_tier() -> None:
    principal = make_principal(tier=AccessTier.REVIEWED)
    assert readable(make_span(tier=AccessTier.REVIEWED), principal) is True
    assert readable(make_span(tier=AccessTier.PUBLIC), principal) is True
