"""Claim/citation verification (ANSWER.md steps 8-9).

Fluent output raises the verification burden rather than lowering it
(arXiv:2602.13855). The unit checked here is the claim, not the answer: an answer
that is 90% cited is an answer with an uncited sentence in it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from korpus.domain.access import Principal, readable
from korpus.domain.models import Citation, Claim, EvidenceSpan


@dataclass(frozen=True)
class VerificationResult:
    coverage: float
    unsupported: tuple[int, ...] = ()
    out_of_range: tuple[int, ...] = ()
    unauthorized: tuple[int, ...] = ()
    empty: bool = False
    limitations: tuple[str, ...] = field(default=())

    @property
    def integrity_breach(self) -> bool:
        """A generator pointing outside the evidence set, or at evidence the caller
        may not read, is a defect — not a low score. It can never be answered past."""
        return bool(self.out_of_range or self.unauthorized)


def verify(
    claims: list[Claim],
    citations: list[Citation],
    evidence: list[EvidenceSpan],
    principal: Principal,
) -> VerificationResult:
    if not claims:
        return VerificationResult(
            coverage=0.0,
            empty=True,
            limitations=("Модель не сформувала жодного твердження з наявних джерел.",),
        )

    unsupported: list[int] = []
    out_of_range: list[int] = []
    unauthorized: list[int] = []
    valid_range = range(len(citations))

    for position, claim in enumerate(claims):
        indexes = claim.citation_indexes
        if not indexes:
            unsupported.append(position)
            continue
        if any(index not in valid_range for index in indexes):
            out_of_range.append(position)
            unsupported.append(position)
            continue
        if any(not readable(evidence[index], principal) for index in indexes):
            unauthorized.append(position)
            unsupported.append(position)

    supported = len(claims) - len(set(unsupported))
    coverage = supported / len(claims)

    limitations: list[str] = []
    if unsupported:
        limitations.append(
            f"Тверджень без підтвердженого джерела: {len(set(unsupported))} із {len(claims)}."
        )
    if out_of_range:
        limitations.append("Виявлено посилання за межі набору доказів.")
    if unauthorized:
        limitations.append("Виявлено посилання на джерело поза рівнем доступу читача.")

    return VerificationResult(
        coverage=coverage,
        unsupported=tuple(sorted(set(unsupported))),
        out_of_range=tuple(out_of_range),
        unauthorized=tuple(unauthorized),
        limitations=tuple(limitations),
    )
