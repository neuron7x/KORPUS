"""Число осі правдиве про свій розподіл входу — і мовчить про той, який справді буде.

Еталон питає називним, бо роль береться із заголовка документа як є: «Які обов'язки має
днювальний парку?». Людина питає родовим: «які обов'язки днювального парку». Виміряно
01.09.2026 на живому продукті — називний 14/14, родовий **1/14**.

Тут перевіряється не пошук, а сам ВИМІРЮВАЧ другої форми: він мусить рахувати ПЕРШУ
цитату й саме той документ, який оголосив цю роль, інакше 0.0714 виявиться властивістю
лінійки, а не системи.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_subject_precision import (  # noqa: E402
    INFLECTION_SET,
    cited_first_is,
    inflection_pairs,
)

ROLE = "Днювальний парку"


def _answer(*titles: str) -> dict[str, object]:
    return {"status": "answered", "citations": [{"title": t} for t in titles]}


def test_the_declaring_document_cited_first_counts() -> None:
    assert cited_first_is(_answer(f"Обов'язки: {ROLE} (Статут, ст.358)"), ROLE)


def test_the_same_document_cited_second_does_not() -> None:
    """Вісь про ПЕРШУ цитату: документ десь у переліку — інша величина."""
    answer = _answer("Обов'язки: Черговий парку (Статут, ст.353)", f"Обов'язки: {ROLE} (ст.358)")

    assert not cited_first_is(answer, ROLE)


def test_a_neighbouring_role_is_not_the_role() -> None:
    """Саме ця підміна й трапляється в родовому: сусідній артикул того ж парку."""
    assert not cited_first_is(_answer("Обов'язки: Черговий парку (Статут, ст.353)"), ROLE)


def test_a_longer_role_that_starts_the_same_is_not_the_role() -> None:
    """«Днювальний парку» не сміє зарахуватись за «Днювальний парку та складу»."""
    assert not cited_first_is(_answer("Обов'язки: Днювальний парку та складу (ст.999)"), ROLE)


def test_the_typographic_apostrophe_is_the_same_role() -> None:
    """Апостроф трапляється двома символами; кодування не є хибною відповіддю."""
    assert cited_first_is(_answer(f"Обов’язки: {ROLE} (Статут, ст.358)"), ROLE)


def test_an_answer_without_citations_is_not_a_hit() -> None:
    assert not cited_first_is(_answer(), ROLE)


def test_an_unreachable_answer_is_not_a_hit() -> None:
    """Недосяжний сервер — не промах пошуку; зарахувати його означало б міряти мережу."""
    assert not cited_first_is(None, ROLE)


def test_the_frozen_set_is_declined_by_hand_and_adjectival_heavy() -> None:
    """Морфологія тут ДАНІ: правило утворення було б думкою про мову всередині лінійки.

    Прикметникових більшість навмисно — саме вони розходяться в стемері, і набір із
    перевагою іменників показував би високе число й не міряв би нічого.
    """
    pairs = inflection_pairs(INFLECTION_SET)

    assert len(pairs) >= 14
    assert all(pair["role"] and pair["genitive"] for pair in pairs)
    assert all(pair["genitive"] != pair["role"].lower() for pair in pairs)
    assert sum(bool(pair["adjectival"]) for pair in pairs) > len(pairs) / 2


def test_every_frozen_role_is_a_subject_the_corpus_declares() -> None:
    """Пара про роль, якої корпус не оголошує, міряла б відсутність, а не відмінок."""
    import sqlite3

    database = ROOT / "var/runtime/corpus-v6-20260807/korpus.db"
    if not database.is_file():  # на свіжому клоні корпусу немає
        return
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    titles = [
        str(row[0]).replace("’", "'")
        for row in connection.execute(
            "SELECT DISTINCT canonical_title FROM documents WHERE canonical_title LIKE 'Обов%'"
        )
    ]
    connection.close()
    missing = [
        pair["role"]
        for pair in inflection_pairs(INFLECTION_SET)
        if not any(t.startswith(f"Обов'язки: {pair['role']} ") for t in titles)
    ]

    assert missing == [], missing


def test_the_set_on_disk_is_readable_as_the_measurer_reads_it() -> None:
    lines = INFLECTION_SET.read_text(encoding="utf-8").splitlines()

    assert [json.loads(line) for line in lines if line.strip()] == inflection_pairs(INFLECTION_SET)


def test_an_empty_run_may_not_overwrite_a_measured_report(tmp_path) -> None:
    """Доказ знищується не хибним числом, а тим, що порожній результат займає місце.

    Виміряно 02.09.2026 на власній помилці: `make subject-precision` не мав чим
    передати токен, тож проти автентифікованого розгортання всі 92 предмети стали
    `unreachable`. Звіт чесно сказав UNKNOWN — і цим ЗАТЕР звіт із `top1: 0.967`.
    Вісь одразу впала в UNMEASURED, і виглядало це як регрес якості.

    «Транспортна відмова не є вимірюванням» у цьому дереві вже записано, але
    боронило воно ЧИСЛО — нуль замість «не міряли». Файл воно не боронило.
    """
    import json

    from benchmark_subject_precision import refuse_to_overwrite_a_measurement

    out = tmp_path / "subject-precision.json"
    out.write_text(json.dumps({"top1_subject_precision": 0.967}), encoding="utf-8")

    with pytest.raises(SystemExit, match="жоден із 92"):
        refuse_to_overwrite_a_measurement(out, unreachable=92, total=92)

    # Дуал 1: ЧАСТКОВА недосяжність проходить — вона лишається в звіті числом,
    # і саме так її видно. Заборонена рівно повна.
    refuse_to_overwrite_a_measurement(out, unreachable=91, total=92)

    # Дуал 2: якщо попереднього виміру немає, порожній прогін має право записатись —
    # інакше перший прогін у чистому дереві був би неможливий.
    empty = tmp_path / "fresh.json"
    refuse_to_overwrite_a_measurement(empty, unreachable=92, total=92)
    unmeasured = tmp_path / "unknown.json"
    unmeasured.write_text(json.dumps({"status": "UNKNOWN"}), encoding="utf-8")
    refuse_to_overwrite_a_measurement(unmeasured, unreachable=92, total=92)
