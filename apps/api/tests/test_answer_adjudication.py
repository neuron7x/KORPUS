"""Чотири незалежні осі судять цитату, і вирок виносить механіка, не згода.

Доктрина взята з `config/agents/axes.json`, де вона вже записана для агентів НАД
системою: агент не верифікує агента — верифікує інша вісь. Дві осі на тих самих даних
це одна вісь за подвійну ціну.

Кожне позитивне твердження тут має негативний контроль. Вісь, яка відхиляє все,
виглядала б найсуворішою і була б непридатною, тому нижче доведено обидва напрямки:
що вісь спрацьовує там, де мусить, і мовчить там, де не мусить.
"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from korpus.application.answer_adjudication import (
    adjudicate,
    is_question,
    presentation,
    question_kind,
)
from korpus.application.answer_query import AnswerPolicy, ExtractiveAnswerService
from korpus.domain.models import Identity, QueryRequest, RetrievedEvidence

from apps.api.tests.helpers import approve, ingest_text

CIVILIAN_QUESTION = "Чи є цивільні обʼєкти законними цілями для нападу?"
SUBSTITUTED = "Воєнні обʼєкти вважаються законними цілями для нападу."
BOTH_CATEGORIES = (
    "Воєнний обʼєкт залишається таким навіть у тому випадку, "
    "якщо на ньому знаходяться цивільні особи."
)
LAYOUT = "«Буг» по цілі А78" + " " * 48 + "вогонь відкрив."
PROSE_WITH_A_GAP = (
    "If the casualty has increased difficulty breathing, lift the chest seal"
    + " " * 19
    + "to release trapped air, then reseal it and wipe away debris around the wound."
)


def _axes(question: str, quote: str, coverage: float = 1.0) -> dict[str, str]:
    return {item.axis: item.verdict for item in adjudicate(question, quote, coverage, 0.5)}


# ── вісь підміни предмета


def test_a_quote_about_the_opposite_category_is_contested() -> None:
    """Різниця між правомірним ураженням і воєнним злочином — одне слово.

    Питання про ЦИВІЛЬНІ обʼєкти, цитата про ВОЄННІ: покриття 0.8, три осі згодні.
    Виміряно на живому розгортанні 31.08.2026 — саме так це й виглядало для читача.
    """
    assert _axes(CIVILIAN_QUESTION, SUBSTITUTED)["contrast"] == "DOES_NOT_SUPPORT"
    assert presentation(adjudicate(CIVILIAN_QUESTION, SUBSTITUTED, 1.0, 0.5)) == "contested"


def test_a_norm_that_names_both_categories_is_not_contested() -> None:
    """Негативний контроль: норма зазвичай згадує обидві категорії, і це не підміна."""
    assert _axes(CIVILIAN_QUESTION, BOTH_CATEGORIES)["contrast"] != "DOES_NOT_SUPPORT"


def test_the_opposite_modality_is_an_answer_not_a_substitution() -> None:
    """Урок, здобутий помилкою в першій редакції цієї ж осі.

    Пара «дозволяється ↔ забороняється» здавалась очевидною і була хибною:
    «Заборонено відкривати вогонь по цивільній особі» — це ВІДПОВІДЬ на питання «коли
    дозволяється», а не мова про інший предмет. Власний тест спростував її за хвилину.
    """
    verdicts = _axes(
        "Коли дозволяється відкривати вогонь по цивільній особі?",
        "Заборонено відкривати вогонь по цивільній особі.",
    )
    assert verdicts["contrast"] != "DOES_NOT_SUPPORT"


# ── вісь верстки


def test_a_column_fragment_is_contested() -> None:
    assert _axes("Коли дозволяється відкривати вогонь?", LAYOUT)["structural"] == "DOES_NOT_SUPPORT"


def test_prose_with_one_wide_gap_is_not_a_column() -> None:
    """Негативний контроль, здобутий виміром, а не уявою.

    Перша редакція дивилась на ФАКТ прогону ≥8 пробілів і відхиляла нормальні речення:
    на замороженому еталоні три кейси перевернулись у `requires_human_review`. Прогін
    48 із 81 символа — колонка; 19 із 211 — речення, у якому PDF лишив слід.
    """
    assert _axes("wiping exhalation reseal", PROSE_WITH_A_GAP)["structural"] != "DOES_NOT_SUPPORT"


# ── вісь типу питання


def test_the_question_type_axis_recognises_what_it_knows() -> None:
    assert question_kind(CIVILIAN_QUESTION) == "permission"
    assert question_kind("Хто відповідає за ведення бойових документів?") == "duty"
    assert question_kind("Скільки триває бойове чергування?") == "quantity"


def test_an_unrecognised_question_type_abstains_rather_than_guesses() -> None:
    """UNKNOWN не є PASS і не є FAIL. Здогад про тип наклав би на джерело вимогу,
    якої воно не зобовʼязане нести."""
    assert question_kind("Розкажи про статут.") is None
    assert _axes("Розкажи про статут.", "Будь-яке речення.")["interrogative"] == "CANNOT_ADJUDICATE"


def test_the_axis_that_can_reject_does_not_judge_a_keyword_bag() -> None:
    """Мішок ключових слів не має предмета, тож підміняти нема чого.

    Захист стоїть саме тут, а не на інтеррогативній осі: та вміє лише схвалювати або
    утримуватись, і мутант, що знімав із неї такий самий захист, ВИЖИВ — бо знімати
    було нічого. Вісь, яка вміє ВІДХИЛЯТИ, без захисту відхиляє мішок слів.
    """
    bag = "цивільні обʼєкти законні цілі напад"

    assert not is_question(bag)
    assert _axes(bag, SUBSTITUTED)["contrast"] == "CANNOT_ADJUDICATE"
    # А те саме, поставлене як питання, вісь відхиляє — інакше тест був би зеленим
    # від того, що вісь мовчить завжди.
    assert _axes(CIVILIAN_QUESTION, SUBSTITUTED)["contrast"] == "DOES_NOT_SUPPORT"


# ── арифметика вироку


def test_one_dissenting_axis_outweighs_the_agreement_of_the_rest() -> None:
    """Вісь, що відхилила, побачила те, куди інші не дивляться."""
    assert presentation(adjudicate(CIVILIAN_QUESTION, SUBSTITUTED, 1.0, 0.5)) == "contested"


def test_a_single_supporting_axis_is_not_a_ground() -> None:
    """Саме одна вісь — лексичне покриття — і давала «ПІДСТАВА Є» рядку про позивний."""
    verdicts = adjudicate("Розкажи про статут.", "ня рани Зупинка кровотечі", 1.0, 0.5)
    assert presentation(verdicts) == "tangential"


# ── поведінка кінець-у-кінець


def _answer(client: TestClient, identity: Identity, text: str, question: str) -> object:
    result = ingest_text(client, text=text)
    approve(client, result["version"]["id"])
    rows = client.app.state.repository.list_retrievable_spans(
        client.identity_provider.current, frozenset({"public"}), date.today()
    )
    span, document, version = rows[0]
    evidence = RetrievedEvidence(
        span=span, document=document, version=version, score=0.95, query_coverage=1.0
    )

    class _Retriever:
        def search(
            self,
            _identity: Identity,
            _text: str,
            _corpus_ids: frozenset[str],
            _as_of: date,
            limit: int = 8,
        ) -> list[RetrievedEvidence]:
            return [evidence]

    service = ExtractiveAnswerService(
        client.app.state.repository,
        _Retriever(),
        client.app.state.policy,
        AnswerPolicy(
            minimum_score=0.05,
            minimum_query_coverage=0.1,
            minimum_support_score=0.05,
            calibration_id="adjudication-test",
        ),
    )
    return service.execute(identity, QueryRequest(text=question))


def test_when_every_citation_is_contested_the_answer_goes_to_a_human(
    client: TestClient, admin_identity: Identity
) -> None:
    answer = _answer(client, admin_identity, SUBSTITUTED, CIVILIAN_QUESTION)

    assert answer.status.value == "requires_human_review"
    assert answer.decision_reason == "all_citations_contested_by_an_independent_axis"
    assert answer.citations[0].presentation == "contested"
    assert answer.citations[0].adjudication_reason


def test_an_uncontested_citation_still_answers(
    client: TestClient, admin_identity: Identity
) -> None:
    """Негативний контроль: правило, що зупиняє все, зупинило б і правильні відповіді."""
    answer = _answer(
        client,
        admin_identity,
        "Начальник складу відповідає за ведення обліку майна.",
        "Хто відповідає за ведення обліку майна?",
    )

    assert answer.status.value == "answered"
    assert answer.citations[0].presentation == "supported"
