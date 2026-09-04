"""Межі `verify_draft`: три гілки, яких не брав жоден прогін.

Вимір покриття гілок 04.09.2026. Усі три — про форму ВХОДУ, а не про правило:
чернетка, склеєна в один рядок; порожнє речення після поділу; порожній відрізок
без змістовних слів. Кожна з них тихо міняє те, ЩО перевіряється, тому мовчазний
пропуск тут дорожчий за помилку.
"""

from __future__ import annotations

import pytest
from korpus.application.composition import verify_draft


def test_a_joined_string_of_passages_is_refused_rather_than_iterated() -> None:
    """Рядок теж послідовність — і саме тому його треба відхилити явно.

    `Sequence[str]` приймає `str`: склеєні прольоти перебиралися б ПОСИМВОЛЬНО, кожен
    символ ставав би окремим «прольотом», словник виродився б у набір літер, і будь-яке
    речення виявилось би підтвердженим. Мовчазна згода замість перевірки.
    """
    with pytest.raises(TypeError, match="not one joined string"):
        verify_draft("Позицію маскують.", "Позицію маскують.")  # type: ignore[arg-type]


def test_trailing_whitespace_does_not_become_an_empty_unsupported_sentence() -> None:
    """Поділ речень лишає порожній хвіст; він не речення й не може бути непідтвердженим.

    Інакше кожна чернетка, що закінчується пробілом, діставала б зайвий вирок
    «корпус не містить» ні про що.
    """
    passages = ["Позицію маскують засобами місцевості."]
    verdicts = verify_draft("Позицію маскують засобами місцевості. ", passages)
    assert len(verdicts) == 1
    assert verdicts[0].supported is True


def test_an_empty_clause_does_not_claim_the_sentence_for_the_wrong_passage() -> None:
    """Порожній відрізок не має змістовних слів — і саме тому не сміє нічого привласнювати.

    Порожня множина слів є підмножиною БУДЬ-ЯКОГО словника, тож без пропуску такий
    відрізок «підтверджується» кожним прольотом, і `carried_by` дістає ПЕРШИЙ із них.
    Речення тоді приписується джерелу, яке його не каже: рівно та вада, проти якої
    існує посилання на цитату. Тут зміст несе лише проліт №1, а речення починається
    з коми, тож приписування мусить лишитись на №1.

    Виміряно 04.09.2026: без сторожа `carried_by` стає 0, і жодна перевірка
    «підтверджено/ні» цього не бачить — різниця тільки в атрибуції.
    """
    passages = ["Турнікет накладають вище рани.", "Позицію маскують засобами місцевості."]
    verdicts = verify_draft(", Позицію маскують засобами місцевості.", passages)
    assert len(verdicts) == 1
    assert verdicts[0].supported is True
    assert verdicts[0].carried_by == 1


def test_a_sentence_the_corpus_does_not_carry_is_still_refused() -> None:
    """Негативне плече: попередні три тести не сміють зробити перевірку поблажливою."""
    passages = ["Позицію маскують засобами місцевості."]
    verdicts = verify_draft("Позицію маскують вертольотом.", passages)
    assert len(verdicts) == 1
    assert verdicts[0].supported is False
