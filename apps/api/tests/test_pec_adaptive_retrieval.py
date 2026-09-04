"""Диспетчер дій адаптивного пошуку: кожна гілка мусить бути виконаною хоч раз.

Вимір покриття гілок 04.09.2026 показав, що три з шести дій контролера ніколи не
виконувались ЖОДНИМ прогоном — ані SQLite, ані PostgreSQL: ENABLE_SEMANTIC_RETRIEVAL,
PLAN_AND_SEMANTIC і запасна гілка. Дія, яку ніхто не пройшов, — це не поведінка
системи, а намір автора.

Усе тут входить ін'єкцією (`search_one`, `search_plan`, `merge`, `observed`), тож
предмет виміру — САМЕ диспетчер, а не пошук під ним.
"""

from __future__ import annotations

from datetime import date

import pytest
from korpus.application.pec_adaptive_retrieval import adaptive_retrieval_impl
from korpus.application.pec_retrieval_types import PECSearchOutcome
from korpus.application.predictive_evidence_control import ControllerTrace, RetrievalAction
from korpus.application.query_plan import QueryPlan
from korpus.application.risk import QueryRisk, RiskThresholds
from korpus.domain.models import AccessTier, Identity, RetrievedEvidence

AS_OF = date(2026, 8, 14)
CORPORA = frozenset({"public"})


def _identity() -> Identity:
    return Identity(
        subject="pec-dispatch-user",
        roles=frozenset({"user"}),
        clearance=AccessTier.PUBLIC,
        corpora=CORPORA,
    )


def _trace(action: object) -> ControllerTrace:
    return ControllerTrace(
        profile_id="dispatch-profile",
        profile_digest="d" * 64,
        state_fingerprint="f" * 64,
        predicted_action=action,  # type: ignore[arg-type]
        effective_action=action,  # type: ignore[arg-type]
        rule_id=None,
        leaf_id=None,
        admitted=True,
        fallback_reason=None,
        shadow_mode=False,
        first_pass_sufficient=False,
    )


class _Controller:
    """Контролер, чиє рішення задане ззовні: диспетчер судиться окремо від політики."""

    def __init__(self, action: object) -> None:
        self.action = action

    def decide(
        self, state: object, *, corpus_release_id: str, answer_calibration_id: str
    ) -> ControllerTrace:
        return _trace(self.action)


class _Calls:
    def __init__(self) -> None:
        self.one: list[dict[str, object]] = []
        self.plan: list[dict[str, object]] = []

    def search_one(
        self,
        retriever: object,
        identity: Identity,
        text: str,
        corpora: frozenset[str],
        as_of: date,
        *,
        semantic_enabled: bool | None = None,
    ) -> list[RetrievedEvidence]:
        self.one.append({"text": text, "semantic_enabled": semantic_enabled})
        return []

    def search_plan(
        self,
        retriever: object,
        identity: Identity,
        plan: QueryPlan,
        corpora: frozenset[str],
        as_of: date,
        *,
        semantic_enabled: bool | None = None,
        include_asked: bool = True,
    ) -> list[RetrievedEvidence]:
        self.plan.append(
            {
                "asked": plan.asked,
                "semantic_enabled": semantic_enabled,
                "include_asked": include_asked,
            }
        )
        return []


def _run(action: object) -> tuple[PECSearchOutcome, _Calls]:
    calls = _Calls()
    outcome = adaptive_retrieval_impl(
        identity=_identity(),
        query_text="накладання турнікету",
        corpora=CORPORA,
        as_of=AS_OF,
        risk=QueryRisk.STANDARD,
        admission_thresholds=RiskThresholds(0.1, 0.1, 0.1, 0.1),
        retriever=object(),  # type: ignore[arg-type]
        planner=None,
        controller=_Controller(action),  # type: ignore[arg-type]
        answer_calibration_id="dispatch-calibration",
        corpus_release_id="a" * 64,
        eligible_count=len,
        outcome_type=PECSearchOutcome,
        observed=lambda outcome, started: outcome,
        search_one=calls.search_one,
        search_plan=calls.search_plan,
        merge=lambda first, second: [*first, *second],
    )
    return outcome, calls


def test_enable_semantic_retrieval_runs_a_second_search_with_semantic_on() -> None:
    """Дія вмикає семантику ДРУГИМ запитом; перший навмисно йде без неї.

    Якби другий запит не позначався `semantic_enabled=True`, дія називалася б
    «увімкнути семантику», нічого не вмикаючи.
    """
    outcome, calls = _run(RetrievalAction.ENABLE_SEMANTIC_RETRIEVAL)
    assert [call["semantic_enabled"] for call in calls.one] == [None, True]
    assert calls.plan == []
    assert outcome.trace is not None
    assert outcome.trace.semantic_executed is True
    assert outcome.trace.planner_executed is False


def test_plan_and_semantic_runs_the_plan_with_semantic_on() -> None:
    """Обидва важелі разом: план будується І виконується семантично."""
    outcome, calls = _run(RetrievalAction.PLAN_AND_SEMANTIC)
    assert len(calls.plan) == 1
    assert calls.plan[0]["semantic_enabled"] is True
    assert outcome.trace is not None
    assert outcome.trace.semantic_executed is True


def test_plan_query_variants_runs_the_plan_without_semantic_and_without_the_asked_text() -> None:
    """Варіанти запиту — без семантики і без повторення вже виконаного питання."""
    _, calls = _run(RetrievalAction.PLAN_QUERY_VARIANTS)
    assert len(calls.plan) == 1
    assert calls.plan[0]["semantic_enabled"] is False or calls.plan[0]["semantic_enabled"] is None
    assert calls.plan[0]["include_asked"] is False


def test_an_action_that_is_not_a_known_member_falls_back_instead_of_raising() -> None:
    """Невідома дія не валить запит — і саме тому мусить бути видимою.

    `RetrievalAction` — StrEnum, а диспетчер порівнює через `is`. Рядок, РІВНИЙ назві
    дії, не є тим самим об'єктом, тож він мине всі гілки й тихо дістане запасну
    поведінку. Тест фіксує наявний стан: система не падає, але й не відмовляє.
    Це поведінка класу «невідоме не є дозволом» — її треба бачити, а не відкрити
    випадково при першій десеріалізації дії з JSON.
    """
    outcome, calls = _run("PLAN_AND_SEMANTIC")
    assert calls.plan == []
    assert [call["semantic_enabled"] for call in calls.one] == [None]
    assert outcome.plan == QueryPlan(asked="накладання турнікету")
    assert outcome.early_abstain is False


@pytest.mark.parametrize(
    ("action", "early_abstain"),
    [(RetrievalAction.STOP_USE_CURRENT_EVIDENCE, False), (RetrievalAction.ABSTAIN, True)],
)
def test_terminal_actions_do_no_further_retrieval(action: RetrievalAction, early_abstain: bool) -> None:
    """Спинитись означає не шукати більше — інакше «стоп» коштує стільки ж, скільки пошук."""
    outcome, calls = _run(action)
    assert len(calls.one) == 1
    assert calls.plan == []
    assert outcome.early_abstain is early_abstain
