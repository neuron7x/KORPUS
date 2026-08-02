"""Authority precedence, validity and supersession (SYSTEM.md retrieval steps 5-6).

Retrieval score answers "how similar"; this module answers "which one governs".
The two are kept apart on purpose: similarity must never outrank authority.
"""

from __future__ import annotations

from datetime import datetime

from korpus.domain.models import AuthorityClass, EvidenceSpan

# Lower rank wins. ADVERSARY material is retained in the corpus for study but is
# never allowed to govern an answer, so it sorts last by construction.
AUTHORITY_RANK: dict[AuthorityClass, int] = {
    AuthorityClass.OFFICIAL_UA: 0,
    AuthorityClass.OFFICIAL_ALLIED: 1,
    AuthorityClass.APPROVED_TRAINING: 2,
    AuthorityClass.MANUFACTURER: 3,
    AuthorityClass.ANALYTICAL: 4,
    AuthorityClass.HISTORICAL: 5,
    AuthorityClass.UNKNOWN: 6,
    AuthorityClass.ADVERSARY: 7,
}

# Classes that may never be cited as governing evidence, regardless of score.
NON_GOVERNING: frozenset[AuthorityClass] = frozenset(
    {AuthorityClass.ADVERSARY, AuthorityClass.UNKNOWN}
)


def is_current(span: EvidenceSpan, now: datetime) -> bool:
    """A span is current when it is neither superseded nor past its validity date."""
    if span.superseded_by is not None:
        return False
    return not (span.valid_until is not None and span.valid_until <= now)


def may_govern(span: EvidenceSpan) -> bool:
    return span.authority not in NON_GOVERNING


def precedence_key(span: EvidenceSpan) -> tuple[int, float, str]:
    """Sort key: authority first, score second, chunk id as a deterministic tiebreak."""
    return (AUTHORITY_RANK[span.authority], -span.retrieval_score, str(span.chunk_id))


def order_by_precedence(spans: list[EvidenceSpan]) -> list[EvidenceSpan]:
    return sorted(spans, key=precedence_key)


def deduplicate_by_version(spans: list[EvidenceSpan]) -> list[EvidenceSpan]:
    """Keep the highest-precedence span per document version.

    Two chunks of the same version repeated in an answer read as two independent
    sources to a human. They are not.
    """
    kept: dict[str, EvidenceSpan] = {}
    for span in order_by_precedence(spans):
        key = str(span.document_version_id)
        if key not in kept:
            kept[key] = span
    return [kept[key] for key in sorted(kept, key=lambda k: precedence_key(kept[k]))]


def conflicting_versions(spans: list[EvidenceSpan]) -> tuple[EvidenceSpan, ...]:
    """Spans of equal top authority drawn from different document *versions*.

    Two live versions of one document are the sharpest conflict there is — that is a
    revision that was never superseded — so keying on document identity alone missed
    exactly the case the function is named after. Exposed rather than hidden:
    SYSTEM.md requires conflicts to be shown, and a silently dropped competing source
    is how a stale order stays in force.
    """
    if not spans:
        return ()
    ordered = order_by_precedence(spans)
    top = AUTHORITY_RANK[ordered[0].authority]
    peers = [s for s in ordered if AUTHORITY_RANK[s.authority] == top]
    versions = {str(s.document_version_id) for s in peers}
    return tuple(peers) if len(versions) > 1 else ()
