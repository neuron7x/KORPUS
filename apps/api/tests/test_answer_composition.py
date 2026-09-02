"""An agent may arrange the evidence and open with one line. It may not add a fact.

The extractive answer is correct and reads badly: four sentences from four manuals, in
retrieval order, starting mid-page. A soldier asking «як накласти турнікет» gets the right
passages in the wrong shape, and the shape decides whether they are read.

So a model composes, and what it may compose is bounded by something checkable rather
than by a prompt. Every test here is an attempt to get a fact past that boundary, because
a prompt is a request and `admissible_opening` is the answer.

Numbers and negation have their own rules, and they are the reason this file exists.
"не менше 30 м" and "не менше 300 м" differ by one character; "дозволяється" and
"не дозволяється" by one word. A gate that only checked that every token appeared
somewhere in the evidence would pass both, because "не" appears in almost every Ukrainian
document and "300" appears in plenty.
"""

from __future__ import annotations

import time

import pytest
from korpus.application.composition import (
    MAX_OPENING_WORDS,
    CompositionRefused,
    admissible_opening,
    compose_answer,
    verify_draft,
)

SPANS = [
    "Джгут накладається вище рани на п'ять сантиметрів.",
    "Час накладання записується на пов'язці пораненого.",
]


class _Composer:
    def __init__(self, opening: str, sentences: list[str] | None = None) -> None:
        self.opening = opening
        self.sentences = sentences

    def compose(self, question: str, sentences: list[str]) -> tuple[str, list[str]]:
        return self.opening, self.sentences if self.sentences is not None else []


def _compose(opening: str, sentences: list[str] | None = None):
    return compose_answer("як накласти джгут", SPANS, _Composer(opening, sentences))


def test_an_opening_made_of_words_in_the_evidence_is_admitted() -> None:
    composition, reason = _compose("Джгут накладається вище рани, час записується")

    assert composition is not None, reason
    assert composition.sentences == tuple(SPANS)


def test_an_opening_that_states_something_the_evidence_does_not_is_refused() -> None:
    """The whole point. A word nobody can check against a quote is a claim."""
    composition, reason = _compose("Джгут накладається на стегнову артерію")

    assert composition is None
    assert "evidence does not" in reason, reason


def test_an_opening_that_states_a_number_is_refused() -> None:
    """Every figure a reader acts on must come from a sentence carrying a hash."""
    composition, reason = _compose("Джгут накладається вище рани на 50 сантиметрів")

    assert composition is None
    assert "number" in reason, reason


@pytest.mark.parametrize("negation", ["не", "без", "заборонено"])
def test_an_opening_that_introduces_a_negation_is_refused(negation: str) -> None:
    """One word flips a norm without changing its vocabulary."""
    composition, reason = _compose(f"Джгут {negation} накладається вище рани")

    assert composition is None
    assert "negation" in reason, reason


def test_dropping_a_retrieved_sentence_is_refused() -> None:
    """A composer that drops evidence decides what the reader does not see."""
    composition, reason = _compose("Джгут накладається вище рани", SPANS[:1])

    assert composition is None
    assert "permutation" in reason, reason


def test_adding_a_sentence_nobody_retrieved_is_refused() -> None:
    composition, reason = _compose(
        "Джгут накладається вище рани", [*SPANS, "Джгут знімається через дві години."]
    )

    assert composition is None
    assert "permutation" in reason, reason


def test_reordering_is_allowed_because_it_invents_nothing() -> None:
    composition, reason = _compose("Джгут накладається вище рани", list(reversed(SPANS)))

    assert composition is not None, reason
    assert composition.sentences == tuple(reversed(SPANS))


def test_a_composer_that_fails_leaves_the_extract_untouched() -> None:
    class _Broken:
        def compose(self, question: str, sentences: list[str]) -> tuple[str, list[str]]:
            raise TimeoutError("provider did not answer")

    composition, reason = compose_answer("питання", SPANS, _Broken())

    assert composition is None
    assert "composer unavailable" in reason


def test_a_blocked_composer_cannot_hold_the_answer_path_past_its_deadline() -> None:
    class _Blocked:
        def compose(self, question: str, sentences: list[str]) -> tuple[str, list[str]]:
            time.sleep(0.4)
            return "late", sentences

    started = time.monotonic()
    composition, reason = compose_answer("питання", SPANS, _Blocked(), deadline_seconds=0.01)

    assert time.monotonic() - started < 0.2
    assert composition is None
    assert "composer exceeded 0.01s deadline" in reason


def test_no_composer_is_the_same_as_a_composer_that_says_nothing() -> None:
    assert compose_answer("питання", SPANS, None)[0] is None


def test_an_opening_longer_than_a_line_is_refused() -> None:
    """A framing line cannot smuggle a claim past a reader who is skimming."""
    words = " ".join(["джгут"] * (MAX_OPENING_WORDS + 1))

    with pytest.raises(CompositionRefused, match="words"):
        admissible_opening(words, SPANS)


def test_the_gate_checks_against_what_the_reader_is_shown() -> None:
    """A line justified by a passage nobody was shown is a line nobody can check."""
    with pytest.raises(CompositionRefused, match="evidence does not"):
        admissible_opening("Джгут накладається на плече", [SPANS[1]])


# ── Три обходи, відтворені 2026-08-31 на чинному коді. Кожен тут як негативний
# контроль: якщо правило приберуть, ці тести червоніють першими.


def test_an_opening_that_borrows_words_from_two_citations_is_refused() -> None:
    """Кожен токен «десь у доказах» — твердження про словник, не про джерело.

    Дві правдиві цитати про вогонь дають словник, у якому складається третє речення,
    якого не каже жодна з них, — і боєць діяв би саме за ним.
    """
    passages = [
        "Вогонь відкривається за командою командира.",
        "Вогонь припиняється за сигналом ракети.",
    ]

    with pytest.raises(CompositionRefused, match="different citations"):
        admissible_opening("Вогонь відкривається за сигналом", passages)


def test_an_opening_carried_by_one_citation_is_admitted() -> None:
    """Негативний контроль до попереднього: сторож, що не приймає нічого, — не сторож."""
    passages = [
        "Вогонь відкривається за командою командира.",
        "Вогонь припиняється за сигналом ракети.",
    ]

    assert admissible_opening("Вогонь відкривається за командою", passages)


def test_a_short_abbreviation_the_evidence_does_not_carry_is_refused() -> None:
    """Військове скорочення має рівно ту форму, яку пропускало правило «менш ніж три»."""
    with pytest.raises(CompositionRefused, match="evidence does not"):
        admissible_opening("Джгут накладається КП", ["Джгут накладається вище рани."])


def test_joined_evidence_is_refused_rather_than_interpreted() -> None:
    """Склеєний рядок — це та сама спільна калюжа слів, лише під іншим ім'ям."""
    with pytest.raises(TypeError, match="joined string"):
        admissible_opening("Джгут накладається", "Джгут накладається вище рани.")


def test_the_reader_is_shown_the_retrieved_span_not_the_composer_string() -> None:
    """Звірка перестановки йде через casefold, тож зміна регістру її проходить.

    Композитор обирає ПОРЯДОК; текст завжди залишається знайденим, бо саме він несе хеш.
    """
    spans = ["Вогонь відкривається за командою командира."]

    class _Shouting:
        def compose(self, question: str, sentences: list[str]) -> tuple[str, list[str]]:
            return "Вогонь відкривається за командою", [item.upper() for item in sentences]

    composition, reason = compose_answer("коли відкривається вогонь", spans, _Shouting())

    assert reason == "admitted"
    assert composition is not None
    assert composition.sentences == tuple(spans)


# ── Перевірка ЧУЖОЇ чернетки. Той самий інваріант, звернений назовні: агент має
# LLM і пише вільно, а тут дізнається, що з написаного корпус підтверджує.

DISTANCE = "Дистанція між машинами не менше 30 метрів."
DUTY = "Начальник варти зобов'язаний знати завдання варти."


def test_a_verbatim_sentence_is_supported() -> None:
    verdicts = verify_draft(DISTANCE, [DISTANCE, DUTY])

    assert [item.supported for item in verdicts] == [True]
    assert verdicts[0].carried_by == 0


def test_a_dropped_negation_inverts_the_norm_and_the_vocabulary_rule_cannot_see_it() -> None:
    """Найважливіший тут, і саме він показав дірку.

    Правило словника бореться з ДОДАВАННЯМ: клауза не сміє нести чужого слова.
    Проти ВИЛУЧЕННЯ воно безсиле за побудовою — прибрати слово не порушує
    вкладення множин. Виміряно 02.09.2026: «менше 30 метрів» замість «не менше
    30 метрів» проходило `_refuse_uncarried_clauses` без жодної скарги.

    Для статуту це різниця між «не ближче» і «ближче», і боєць діяв би за другим.
    """
    from korpus.application.composition import _refuse_uncarried_clauses

    inverted = "Дистанція між машинами менше 30 метрів."
    # Старе правило мовчить — це негативний контроль ДІРКИ, не нового правила.
    _refuse_uncarried_clauses(inverted, [DISTANCE])

    verdict = verify_draft(inverted, [DISTANCE])[0]
    assert verdict.supported is False
    assert "знято заперечення" in (verdict.reason or "")


def test_a_foreign_number_is_caught_by_the_vocabulary_rule_alone() -> None:
    """Числа окремої заборони НЕ потребують — і це виміряно, а не припущено.

    `admissible_opening` забороняє будь-яку цифру, бо боронить рядок обрамлення,
    якому цифри не потрібні. У чернетці вони законні: приходять із корпусу.
    Заборонити їх і тут означало б покарати ту саму невизначеність удруге.
    """
    verdict = verify_draft("Дистанція між машинами не менше 300 метрів.", [DISTANCE])[0]

    assert verdict.supported is False
    assert "300" in (verdict.reason or "")


def test_words_pooled_from_two_citations_are_refused() -> None:
    verdict = verify_draft("Начальник варти зобов'язаний знати дистанція.", [DISTANCE, DUTY])[0]

    assert verdict.supported is False
    assert "РІЗНИХ цитат" in (verdict.reason or "")


def test_a_word_no_citation_carries_is_refused() -> None:
    verdict = verify_draft("Начальник варти має право на відпустку.", [DUTY])[0]

    assert verdict.supported is False
    assert "не містить" in (verdict.reason or "")


def test_the_verdict_is_per_sentence_not_wholesale() -> None:
    """Гуртовий вирок марний: агент мусить знати, ЯКЕ речення викинути."""
    draft = f"{DISTANCE} Начальник варти має право на відпустку. {DUTY}"

    verdicts = verify_draft(draft, [DISTANCE, DUTY])

    assert [item.supported for item in verdicts] == [True, False, True]


def test_a_negation_elsewhere_in_a_long_citation_does_not_refuse_everything() -> None:
    """Дуал: перевірка, що відхиляє все, не є перевіркою.

    Правило дивиться на БЕЗПОСЕРЕДНЄ сусідство, а не на присутність «не» будь-де
    в цитаті. Інакше довга цитата з одним запереченням робила б непідтвердженим
    геть усе, що з неї цитують.
    """
    passage = "Вартовий зобов'язаний пильно охороняти пост і не залишати його."

    assert verify_draft("Вартовий зобов'язаний пильно охороняти пост.", [passage])[0].supported


def test_a_word_that_appears_both_negated_and_free_is_not_treated_as_negated() -> None:
    """Одна вільна поява знімає підозру — інакше правило б угадувало."""
    passage = "Вогонь відкривається за командою. Вогонь не відкривається без команди."

    assert verify_draft("Вогонь відкривається за командою.", [passage])[0].supported
