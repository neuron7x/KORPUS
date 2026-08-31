"""Single source of truth for first-pass evidence admission and boundary margins.

PEC/DGC must reason about the *same* gate that the answer runtime will apply.  This
module therefore owns the numeric/structural retrieval admission predicate and exposes
signed margins to that predicate.  A positive minimum margin means the candidate is on
the admitted side of every numeric boundary; a negative value identifies how far the
best structurally valid candidate remains from admission.
"""

from __future__ import annotations

from dataclasses import dataclass

from korpus.application.retrieval import AUTHORITY_PRIOR
from korpus.application.risk import RiskThresholds
from korpus.domain.models import RetrievedEvidence


@dataclass(frozen=True, slots=True)
class CandidateAdmissionMargins:
    score: float
    query_coverage: float
    authority: float

    @property
    def minimum(self) -> float:
        return min(self.score, self.query_coverage, self.authority)


@dataclass(frozen=True, slots=True)
class AdmissionBoundarySummary:
    structural_candidate_exists: bool
    retrieval_gate_passed: bool
    best_score_margin: float
    best_query_coverage_margin: float
    best_authority_margin: float
    minimum_admission_margin: float
    decision_boundary_distance: float


def structurally_admissible(item: RetrievedEvidence) -> bool:
    return item.version.review_state.value == "approved" and item.version.authority.is_normative


def candidate_margins(
    item: RetrievedEvidence,
    thresholds: RiskThresholds,
) -> CandidateAdmissionMargins:
    return CandidateAdmissionMargins(
        score=item.score - thresholds.minimum_score,
        query_coverage=item.query_coverage - thresholds.minimum_query_coverage,
        authority=AUTHORITY_PRIOR[item.version.authority] - thresholds.minimum_authority,
    )


def evidence_is_eligible(
    item: RetrievedEvidence,
    thresholds: RiskThresholds,
    *,
    declares_the_subject: bool = False,
) -> bool:
    """Чи допускається цей уривок до відповіді.

    `declares_the_subject` знімає лексичні пороги — і НЕ знімає структурних.
    Затвердженість версії та нормативність авторитету стоять для всіх однаково:
    допуск за предметом каже «це про того, кого спитали», а не «цьому можна більше».

    Навіщо виняток. Стаття, чий ОГОЛОШЕНИЙ предмет є предметом питання, не повторює
    ані своєї назви, ані слова «обов'язки»: заголовок каже «Обов'язки: Вивідний»,
    текст каже «охороняти за наказом начальника варти». Виміряно 31.08.2026 на
    живому розгортанні: правильна стаття приходила з пошуку ПЕРШОЮ (оцінка 0.181,
    покриття 0.00) і саме тут викидалась порогом 0.25, бо низька оцінка спричинена
    рівно тією сліпотою, проти якої поріг поставлено. На 92 предмети перша цитата
    жодного разу не була документом про предмет.

    Це клас, а не вага: збіг береться з ЗАКРИТОГО словника — 101 заголовок, який
    корпус оголосив про себе сам, — тож обійти його підбором формулювання не можна.
    """
    if not structurally_admissible(item):
        return False
    if declares_the_subject:
        return True
    margins = candidate_margins(item, thresholds)
    return margins.minimum >= 0.0


def eligible_evidence(
    evidence: list[RetrievedEvidence],
    thresholds: RiskThresholds,
    subject_documents: frozenset[str] = frozenset(),
) -> list[RetrievedEvidence]:
    return [
        item
        for item in evidence
        if evidence_is_eligible(
            item, thresholds, declares_the_subject=str(item.document.id) in subject_documents
        )
    ]


def admission_boundary_summary(
    evidence: list[RetrievedEvidence],
    thresholds: RiskThresholds,
) -> AdmissionBoundarySummary:
    structural = [item for item in evidence if structurally_admissible(item)]
    if not structural:
        return AdmissionBoundarySummary(
            structural_candidate_exists=False,
            retrieval_gate_passed=False,
            best_score_margin=-1.0,
            best_query_coverage_margin=-1.0,
            best_authority_margin=-1.0,
            minimum_admission_margin=-1.0,
            decision_boundary_distance=1.0,
        )

    candidates = [(candidate_margins(item, thresholds), item) for item in structural]
    best, _ = max(
        candidates,
        key=lambda pair: (
            pair[0].minimum,
            pair[0].score,
            pair[0].query_coverage,
            pair[0].authority,
            pair[1].score,
            pair[1].query_coverage,
            str(pair[1].span.id),
        ),
    )
    minimum = best.minimum
    return AdmissionBoundarySummary(
        structural_candidate_exists=True,
        retrieval_gate_passed=minimum >= 0.0,
        best_score_margin=best.score,
        best_query_coverage_margin=best.query_coverage,
        best_authority_margin=best.authority,
        minimum_admission_margin=minimum,
        decision_boundary_distance=abs(minimum),
    )
