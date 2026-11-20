"""Deterministic sentence offers within the retrieved evidence budget."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from korpus.application.answer_adjudication import adjudicate, presentation
from korpus.application.answer_analysis import SentenceCandidate, contains_control_injection
from korpus.application.declared_subject import subject_tokens
from korpus.application.evidence import starts_mid_sentence
from korpus.application.evidence_admission import coverage_admits
from korpus.application.question_obligations import QuestionObligations
from korpus.application.risk import RiskThresholds
from korpus.domain.models import RetrievedEvidence

MAX_QUOTE_CHARS = 1600
_PRESENTATION_RANK = {"supported": 0, "tangential": 1, "contested": 2}


@dataclass(frozen=True)
class CandidateOffer:
    evidence: RetrievedEvidence
    candidate: SentenceCandidate
    declared: frozenset[str]


def _sentence_order(
    candidate: SentenceCandidate, question: str, minimum_coverage: float, declared: bool
) -> tuple[int, bool, float, int]:
    verdicts = adjudicate(
        question,
        candidate.text,
        candidate.query_coverage,
        minimum_coverage,
        subject_declared=declared,
    )
    return (
        _PRESENTATION_RANK[presentation(verdicts)],
        starts_mid_sentence(candidate.text),
        -candidate.query_coverage,
        candidate.start,
    )


def _passing(
    offered: list[SentenceCandidate], question: str, minimum_coverage: float, declared: bool
) -> list[SentenceCandidate]:
    passing = [
        candidate
        for candidate in offered
        if coverage_admits(candidate.query_coverage, minimum_coverage)
    ]
    if declared and not passing:
        by_type = [
            candidate
            for candidate in offered
            if any(
                verdict.axis == "interrogative" and verdict.verdict == "SUPPORTS"
                for verdict in adjudicate(
                    question,
                    candidate.text,
                    candidate.query_coverage,
                    minimum_coverage,
                    subject_declared=True,
                )
            )
        ]
        passing = by_type or list(offered)
    return sorted(
        passing, key=lambda item: _sentence_order(item, question, minimum_coverage, declared)
    )


def _evidence_order(item: RetrievedEvidence) -> tuple[int, float, str, int, str]:
    return (item.rank, -item.score, item.version.source_hash, item.span.ordinal, str(item.span.id))


def _one_version(
    offers: list[CandidateOffer], obligations: QuestionObligations
) -> list[CandidateOffer]:
    """Prefer a complete same-version witness; never join unrelated versions."""
    groups: dict[str, list[CandidateOffer]] = {}
    for offer in offers:
        if obligations.facet_hits(offer.candidate.text, offer.declared):
            groups.setdefault(str(offer.evidence.version.id), []).append(offer)
    if not groups:
        return []

    def group_order(group: list[CandidateOffer]) -> tuple[int, tuple[int, float, str, int, str]]:
        covered = set().union(
            *(obligations.facet_hits(item.candidate.text, item.declared) for item in group)
        )
        return (-len(covered), _evidence_order(group[0].evidence))

    remaining = min(groups.values(), key=group_order).copy()
    selected: list[CandidateOffer] = []
    covered: set[int] = set()
    while remaining:
        # Stable min keeps the adjudication/whole-sentence preference on equal gain.
        winner = min(
            remaining,
            key=lambda item: (
                -len(obligations.facet_hits(item.candidate.text, item.declared) - covered)
            ),
        )
        gain = obligations.facet_hits(winner.candidate.text, winner.declared) - covered
        if not gain:
            break
        selected.append(winner)
        covered.update(gain)
        remaining.remove(winner)
    return selected


def candidate_offers(
    eligible: list[RetrievedEvidence],
    query_tokens: frozenset[str],
    thresholds: RiskThresholds,
    question: str,
    obligations: QuestionObligations,
    candidates: Callable[[str, frozenset[str]], list[SentenceCandidate]],
) -> list[CandidateOffer]:
    offers = []
    for item in sorted(eligible, key=_evidence_order):
        declared = frozenset(
            subject_tokens([item.document.canonical_title]).intersection(query_tokens)
        )
        remaining = query_tokens - declared
        effective = remaining if declared and remaining else query_tokens
        offered = [
            candidate
            for candidate in candidates(item.span.text, effective)
            if len(candidate.text) <= MAX_QUOTE_CHARS
            and not contains_control_injection(candidate.text)
            and not obligations.missing_subjects(candidate.text, declared)
            and (not obligations.facets or obligations.facet_hits(candidate.text, declared))
        ]
        for candidate in _passing(
            offered, question, thresholds.minimum_query_coverage, bool(declared)
        ):
            offers.append(CandidateOffer(item, candidate, declared))
    return _one_version(offers, obligations) if obligations.multi_facet else offers
