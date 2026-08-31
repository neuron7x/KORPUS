"""Документ, чий предмет оголошено в заголовку, не повторює його в тілі.

Виміряно 31.08.2026 на живому розгортанні: на 92 предмети, які корпус оголошує
заголовками «Обов'язки: <роль>», перша цитата була документом про цей предмет
**0 разів**. Не 40 %, не «іноді» — нуль.

Причина не одна стадія, а чотири поспіль, і всі винагороджують ПОВТОР слів питання:
кандидати FTS, ранжування, поріг покриття, добір речень. Стаття «Обов'язки: Вивідний»
каже «охороняти за наказом начальника варти» — жодного спільного токена з питанням
«Які обов'язки має Вивідний?». Її сира оцінка 0.181 найнижча у видачі саме тому, що
вона Й Є відповіддю.

Після правок: top1 0.000 → 0.826, recall 0.348 → 0.978, `confidence_inverted`
TRUE → FALSE. Заморожений еталон (93/95) і межа домену (0.95 / 0.20) без змін.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from korpus.application.answer_adjudication import adjudicate
from korpus.application.declared_subject import declared_subject, subjects_in_question

DAY = date(2026, 8, 31)

TITLE = "Обов'язки: Вивідний (Статут, ст.244)"
BODY = "охороняти за наказом начальника варти заарештованих під час прогулянки"


def test_the_corpus_declares_its_own_subjects() -> None:
    """Набір закритий: предмет береться із заголовка, а не з питання.

    Тому обійти допуск переформулюванням не можна — щоб потрапити в множину, документ
    мусить існувати в корпусі й оголосити предмет сам.
    """
    assert declared_subject(TITLE) == "Вивідний"
    assert subjects_in_question("Які обов'язки має Вивідний?", [TITLE]) == [TITLE]


def test_a_question_about_someone_else_does_not_match() -> None:
    """Негативний контроль: інакше допуск ставав би шумом."""
    assert subjects_in_question("Які обов'язки має Начальник варти?", [TITLE]) == []


def test_the_lexical_axis_abstains_where_it_is_structurally_blind() -> None:
    """Нульове покриття тут — властивість ОСІ, а не документа.

    Заперечувати нею означало б позначити спірною кожну статтю, яка й є відповіддю.
    Утримання не підвищує впевненість: щоб цитата стала `supported`, її мусять схвалити
    дві ІНШІ осі.
    """
    verdicts = {
        item.axis: item.verdict
        for item in adjudicate("Які обов'язки має Вивідний?", BODY, 0.0, 0.5, subject_declared=True)
    }

    assert verdicts["lexical"] == "CANNOT_ADJUDICATE"


def test_the_same_passage_without_a_declared_subject_is_still_contested() -> None:
    """Негативний контроль до попереднього: правило звужене до оголошеного предмета."""
    verdicts = {
        item.axis: item.verdict
        for item in adjudicate("Які обов'язки має Вивідний?", BODY, 0.0, 0.5)
    }

    assert verdicts["lexical"] == "DOES_NOT_SUPPORT"


# ── Ланка, яка й тримала нуль зі ста одного


def test_the_plan_search_keeps_the_order_the_ranker_built() -> None:
    """`_search_plan` пересортовував за СИРОЮ оцінкою — і тим скасовував ранжування.

    `diversify_evidence` будує порядок лексикографічно: клас спершу, схожість лише як
    тайбрейк усередині класу, «no amount of lexical similarity promotes a weaker source
    above a stronger one». Рядок нижче за течією робив рівно те, що цей коментар
    забороняє. Та сама вада була в `_merge` і там уже виправлена — але саме ЦЯ функція
    стоїть на шляху розгортання: без каліброваного контролера `adaptive_retrieval_impl`
    повертає `search_plan(...)` першим же рядком.

    Фікстура навмисно легка: функція торкається лише `span.id` і `score`, а повна
    доменна модель сюди не додала б нічого, крім довжини.
    """
    from types import SimpleNamespace

    from korpus.application.pec_retrieval import _search_plan

    weak = SimpleNamespace(span=SimpleNamespace(id=uuid4(), ordinal=1), score=0.18)
    strong = SimpleNamespace(span=SimpleNamespace(id=uuid4(), ordinal=2), score=0.77)

    class _Retriever:
        def search(self, identity, text, corpora, as_of, limit=8):
            return [weak, strong]

    ordered = _search_plan(
        _Retriever(), None, SimpleNamespace(searches=["п"], variants=[]), frozenset({"public"}), DAY
    )

    assert [item.score for item in ordered] == [0.18, 0.77], (
        "порядок пересортовано за оцінкою — правильний документ із найнижчою сирою "
        "оцінкою поїхав у хвіст, і саме так народжувався нуль зі ста одного"
    )
