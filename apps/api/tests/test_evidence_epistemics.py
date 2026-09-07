"""П'ять осей епістеміки доказу, і кожна виявляється лише своїм експериментом.

За дві доби кампанії 05–07.09.2026 знайдено близько сорока вад. Вони не окремі: це
пʼять родів, і жоден із чотирьох експериментів не бачить пʼятого. Тест тримає саме цю
властивість — що осі не зводяться одна до одної, — а не перелік знахідок.

Головне про цей гейт: **перші три його редакції були винні в тому, що він ловить.**
Матчер судив ІМЕНА полів, і три рази поспіль оголошував беззнаменниковими артефакти,
які знаменник несли (`questions_measured`, потім `python`/`web`, потім
`references`/`controls`). Ловилось це лише ручною звіркою свідків — тобто негативним
контролем самої таксономії. Тому регресії на власні хибнопозитиви тут окремими тестами.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "check_evidence_epistemics", ROOT / "scripts/check_evidence_epistemics.py"
)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def test_a_verdict_over_an_empty_population_is_named() -> None:
    """`all([])` істинне: гейт над порожньою множиною зелений саме в тому стані,
    заради якого існує. Це не «бракує поля» — це вирок без предмета."""
    assert GATE.empty_quantifier({"status": "PASS", "checks": {}}) is True
    assert GATE.empty_quantifier({"status": "PASS", "checks": {"a": True}}) is False


def test_a_failing_verdict_over_zero_is_not_the_same_defect() -> None:
    """Дуал: FAIL над нулем — це чесна відмова, не порожній квантор."""
    assert GATE.empty_quantifier({"status": "FAIL", "checks": {}}) is False


def test_the_counter_is_judged_by_exclusion_not_inclusion() -> None:
    """Перелік слів для «скільки одиниць» ВІДКРИТИЙ — його поповнює кожен новий автор.
    Перелік величин часу, розміру й тотожності ЗАМКНЕНИЙ. Тому вісь судить виключенням.

    Три редакції судили включенням і дали 60 % хибнопозитивів на реальному дереві.
    """
    assert GATE.judged_population({"references": 15}) == 15
    assert GATE.judged_population({"questions_measured": 20}) == 20
    assert GATE.judged_population({"rto_seconds": 12}) == 0
    assert GATE.judged_population({"plaintext_bytes": 274903040}) == 0
    assert GATE.judged_population({"source_tree_sha256": 999}) == 0


def test_prose_is_not_a_population() -> None:
    assert GATE.judged_population({"interpretation": "довгий текст", "note": "ще"}) == 0


def test_provenance_is_found_nested() -> None:
    """Перевірка бачила не предмет, а місце, де звикла його бачити: `recovery-report`
    несе `provenance.measured_at`, і перша редакція оголосила його безпохідним."""
    assert GATE.has_provenance({"provenance": {"measured_at": "2026-09-07"}}) is True
    assert GATE.has_provenance({"a": {"b": {"c": {"measured_at": "x"}}}}) is False


def test_a_stale_subject_is_distinguished_from_an_absent_one() -> None:
    """Три різні стани, які легко злити в один: назвав і збігається, назвав і
    розійшовся, не назвав узагалі. Третій — не «не збігається»."""
    assert GATE.subject_is_current({"source_tree_sha256": "b" * 64}, "b" * 64) is True
    assert GATE.subject_is_current({"source_tree_sha256": "c" * 64}, "b" * 64) is False
    assert GATE.subject_is_current({}, "b" * 64) is None


def test_the_five_axes_are_not_reducible_to_one_another() -> None:
    """Незалежність осей — твердження, і воно перевірне.

    Свідок осі — артефакт, що має чотири інші й не має цієї. Вісь без свідка не доведена
    як незалежна: вона або зайва, або її предмет тут не трапляється. Тест вимагає, щоб
    механізм пошуку свідків працював, а не щоб свідки конче знайшлись — інакше він
    червонів би від чистого дерева, що є хибним приводом.
    """
    rows = [
        {"artifact": f"a{i}.json", **{axis: (axis != missing) for axis in GATE.AXES}}
        for i, missing in enumerate(GATE.AXES)
    ]
    verdict = GATE.independence(rows)
    assert verdict["axes_without_witness"] == []
    assert set(verdict["witnesses"]) == set(GATE.AXES)


def test_an_axis_with_no_witness_is_reported_not_hidden() -> None:
    """Негативний контроль таксономії: якщо вісь нічого не розрізняє, гейт мусить це
    СКАЗАТИ, а не мовчки її зарахувати."""
    rows = [{"artifact": "a.json", **dict.fromkeys(GATE.AXES, True)}]
    assert set(GATE.independence(rows)["axes_without_witness"]) == set(GATE.AXES)
