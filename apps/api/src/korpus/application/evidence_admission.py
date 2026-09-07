"""Single source of truth for first-pass evidence admission and boundary margins.

PEC/DGC must reason about the *same* gate that the answer runtime will apply.  This
module therefore owns the numeric/structural retrieval admission predicate and exposes
signed margins to that predicate.  A positive minimum margin means the candidate is on
the admitted side of every numeric boundary; a negative value identifies how far the
best structurally valid candidate remains from admission.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from korpus.application.retrieval import AUTHORITY_PRIOR
from korpus.application.risk import RiskThresholds
from korpus.domain.models import RetrievedEvidence


def coverage_admits(coverage: float, floor: float) -> bool:
    """Чи покриває цитата ПОНАД поріг питання. Рівність — не допуск.

    `query_coverage` — це частка малих цілих: питання має два-чотири змістовні токени,
    тож досяжні значення 0, 1/4, 1/3, 1/2, 2/3, 3/4, 1. Поріг 0.5 лежить РІВНО на
    досяжному значенні, і «рівно на порозі» тут не крайовий випадок, а щільна подія.

    Виміряно 07.09.2026 на замороженому наборі `evals/datasets/domain_boundary.jsonl`,
    на живому розгортанні, усі 40 питань:

        чужі, що прорвались     out-07 out-08 out-09 out-19 — покриття РІВНО 0.50, усі 4
        свої, що відповіли      19 із 19 — покриття 0.67, 0.75 або 1.00, жодного на 0.50

    Тобто клас нічиєї цілком складався з питань не про цей корпус. Цитата, яка лишає
    рівно половину питання без відповіді, стосується не спитаного рівно настільки ж,
    наскільки спитаного, — і вирішувати нічию на користь відповіді означає для
    fail-closed системи обирати гірший бік помилки.

    Це не новий поріг: докстрінг модуля завжди казав «a POSITIVE minimum margin means
    the candidate is on the admitted side». Нуль не описаний ніде, а код мовчки
    зараховував його до допущених. Тут прибрано саме цей неназваний третій випадок.
    """
    return coverage > floor


@dataclass(frozen=True, slots=True)
class CandidateAdmissionMargins:
    score: float
    query_coverage: float
    authority: float

    @property
    def minimum(self) -> float:
        return min(self.score, self.query_coverage, self.authority)

    @property
    def admitted(self) -> bool:
        """Допуск. Нуль маржі допустимий на осях КЛАСУ й неприпустимий на осі покриття.

        Це ТОЙ САМИЙ предикат, що його читає `admission_boundary_summary`, а не переказ:
        PEC/DGC мусять міркувати про гейт, який справді застосує рантайм. Наслідок видно
        у звіті — `minimum_admission_margin` буває нулем при хибному
        `retrieval_gate_passed`, бо нульова маржа покриття і Є відмовою.

        `minimum_authority` набуває значень 0.74, 0.46 і 0.0 — точно рівних пріоритетам
        `APPROVED_TRAINING`, `ANALYTICAL` та `UNKNOWN`. Нульова маржа авторитету означає
        «рівно той клас, який і є найнижчим допустимим», тобто НАВМИСНЕ включення; майже
        весь корпус — `ANALYTICAL`, і строгість тут вимкнула б його цілком. Оцінка ж
        неперервна, і рівність на ній практично не трапляється.

        Тому строгою є рівно одна вісь — та, на якій нічия і виміряна.
        """
        return self.score >= 0.0 and self.authority >= 0.0 and self.query_coverage > 0.0


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
    return candidate_margins(item, thresholds).admitted


def eligible_evidence(
    evidence: list[RetrievedEvidence],
    thresholds: RiskThresholds,
    subject_documents: Mapping[str, int] | frozenset[str] = frozenset(),
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
        retrieval_gate_passed=best.admitted,
        best_score_margin=best.score,
        best_query_coverage_margin=best.query_coverage,
        best_authority_margin=best.authority,
        minimum_admission_margin=minimum,
        decision_boundary_distance=abs(minimum),
    )
