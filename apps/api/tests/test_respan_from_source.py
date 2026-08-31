"""Ремонт нарізки на місці зберіг власний інваріант і зруйнував властивість під ним.

`recut_span_boundaries.py` переносив провідний уламок речення в попередній проліт і
перевіряв, що конкатенація прольотів версії не змінилась. Інваріант тримався на всіх 256
версіях. Вимір 31.08.2026 показав ціну: 23 689 із 38 863 прольотів (60.96 %) перестали бути
підрядком свого джерела, і 9 389 швів склеїли по дві літери в слова, яких у документі немає
— `stabilityttacks`, `andontact`, `Servicexperiencing`.

Інваріант «сума незмінна» зберігається при перенесенні символів між сусідами ЗАВЖДИ. Він
математично не здатен побачити цю ваду — і саме тому був обраний.

Тому нарізка робиться заново з оригіналу, а перевіряються ДВІ речі одразу: кожен проліт є
зрізом джерела за координатами, і прольоти покривають джерело без дірок. Поодинці кожну
можна вдовольнити ціною іншої: викидання 8.4 % корпусу давало той самий бал межі речення,
що й акуратний ремонт.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from respan_from_source import cut_points, verify  # noqa: E402

BODY = "Перше речення тут. Друге речення тут! Третє речення тут? " * 40


def test_every_span_is_a_slice_of_the_source_by_construction() -> None:
    spans = cut_points(BODY, limit=200, overlap=40)

    assert spans
    assert all(BODY[start:end] in BODY for start, end in spans)


def test_the_spans_cover_the_source_with_no_hole() -> None:
    """Дірка — це текст, якого читач не побачить ніколи, і жоден пошук не знайде."""
    spans = cut_points(BODY, limit=200, overlap=40)

    assert verify(BODY, spans, limit=200) == []
    assert spans[0][0] == 0
    assert spans[-1][1] == len(BODY)


def test_a_hole_is_refused_rather_than_written() -> None:
    """Негативний контроль на саму перевірку: сторож, що не бачить дірки, не сторож."""
    assert verify("абвгд", [(0, 2), (3, 5)], limit=10)
    assert verify("абвгд", [(0, 3)], limit=10)


def test_no_span_exceeds_the_ceiling_the_corpus_was_built_with() -> None:
    """Стелю не піднімати заради балу: 1400 → 1600 давало +0.20 без нового тексту."""
    assert all(end - start <= 200 for start, end in cut_points(BODY, limit=200, overlap=40))


def test_a_span_opens_on_a_sentence_and_not_on_a_space() -> None:
    spans = cut_points(BODY, limit=200, overlap=40)

    assert all(not BODY[start].isspace() for start, _ in spans)
    assert all(start == 0 or BODY[start - 1].isspace() for start, _ in spans)


def test_a_sentence_longer_than_the_ceiling_is_split_and_still_covers_everything() -> None:
    """Речень довших за стелю 331 із 357 250. Вони ріжуться, і це видно, а не ховається."""
    monster = "А" * 500 + ". " + "Б" * 30
    spans = cut_points(monster, limit=200, overlap=40)

    assert verify(monster, spans, limit=200) == []
    assert all(end - start <= 200 for start, end in spans)


def test_a_span_over_the_ceiling_is_refused_by_the_check_not_only_avoided_by_the_cutter() -> None:
    """Стелю мусить боронити ПЕРЕВІРКА, а не лише акуратність різака.

    Різак, що випадково не перевищив стелю, і перевірка, що перевищення бачить, — різні
    твердження. Попередній ремонт меж уже одного разу віддав прольот понад стелю, і це
    дало цитату довшу за 1600 символів та HTTP 500 на живому запиті.
    """
    assert verify("абвгд", [(0, 5)], limit=3)


def test_an_empty_source_yields_no_spans_rather_than_one_empty_span() -> None:
    assert cut_points("", limit=200, overlap=40) == []
