"""Гейт, що робить виконуваним правило «стелю можна лише знижувати».

Правило записане в `module-budget.json` словами з першого дня, і до 30.08.2026
його не читав жоден код. Стелю можна було підняти мовчки. Виміряно: 97 із 516
модулів мали стелю вище дефолту без причини, а записи в `raised` існували в
шести формах.

Тому гейт охороняє не минуле, а майбутнє: наявні стелі — база, відмова лише
новому підняттю без причини. Тести тут перевіряють саме цю межу з обох боків.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check_budget_raises_are_named.py"
SPEC = importlib.util.spec_from_file_location("budget_raises", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _doc(lines: int, raised: list | None = None) -> dict:
    return {"modules": {"a.py": {"lines": lines}}, "raised": raised or []}


def test_silent_raise_is_refused() -> None:
    """Головний випадок: стеля зросла, причини ніде немає."""
    offenders = MODULE.raises_without_a_reason(_doc(100), _doc(150))
    assert offenders and "a.py" in offenders[0] and "100→150" in offenders[0]


def test_named_raise_is_allowed() -> None:
    after = _doc(
        150, [{"on": "2026-08-30", "path": "a.py", "reason": "чому", "to": {"lines": 150}}]
    )
    assert MODULE.raises_without_a_reason(_doc(100), after) == []


def test_lowering_needs_no_reason() -> None:
    """Ратчет існує, щоб рухатись УНИЗ. Вимагати причини для зниження означало б
    зробити чесність дорожчою за мовчання."""
    assert MODULE.raises_without_a_reason(_doc(150), _doc(100)) == []


def test_unchanged_ceiling_is_not_a_raise() -> None:
    assert MODULE.raises_without_a_reason(_doc(100), _doc(100)) == []


def test_a_new_module_sets_its_first_ceiling_rather_than_raising_one() -> None:
    """Модуля не було — отже нічого не піднято. Інакше кожен новий файл вимагав би
    запису про підняття стелі, якої в нього ніколи не було."""
    before = {"modules": {}, "raised": []}
    assert MODULE.raises_without_a_reason(before, _doc(900)) == []


def test_every_ceiling_key_is_watched_not_only_lines() -> None:
    """Складність і форма функцій — теж стелі. Гейт, що дивиться лише на рядки,
    пропустив би підняття складності, а саме воно й робить модуль нечитаним."""
    for key in ("max_complexity", "max_function_lines", "max_function_args", "max_nesting"):
        before = {"modules": {"a.py": {key: 5}}, "raised": []}
        after = {"modules": {"a.py": {key: 9}}, "raised": []}
        assert MODULE.raises_without_a_reason(before, after), f"{key} не охороняється"


def test_all_six_record_shapes_count_as_naming() -> None:
    """`raised` накопичив шість форм історично. Вимагати однієї означало б
    відкинути записи, зроблені сумлінно, — гейт вимагає ПРИЧИНИ, не формату.

    Форма лишається вільною, ЧИСЛО — ні: запис мусить назвати стелю, до якої
    піднімають. Раніше цей тест приймав форми БЕЗ числа, і саме він ніс сліпоту,
    описану в `test_a_record_for_another_number_does_not_excuse_this_raise`.
    """
    shapes = [
        {"path": "a.py", "on": "x", "reason": "r", "to": {"lines": 150}},
        {"paths": ["a.py"], "on": "x", "reason": "r", "to": {"lines": 150}},
        {"entries": [{"path": "a.py", "to": {"lines": 150}}], "on": "x", "reason": "r"},
        {"changes": [{"path": "a.py"}], "on": "x", "reason": "r", "to": {"lines": 150}},
    ]
    for shape in shapes:
        assert MODULE.raises_without_a_reason(_doc(100), _doc(150, [shape])) == [], shape


def test_a_record_for_another_number_does_not_excuse_this_raise() -> None:
    """Гейт питав «чи згадано ФАЙЛ», а мусить питати «чи записано САМЕ ЦЕ підняття».

    Виміряно 31.08.2026 на самому репозиторії: `scripts/run_mutation_tests.py` мав
    у `raised` вісім записів за попередні дні, тож підняття 4400 → 4494 пройшло з
    вердиктом PASS і порожнім `unnamed_raises`. Один раз названий файл ставав
    вільним НАЗАВЖДИ, і таких файлів у списку було стільки ж, скільки записів.
    """
    stale = [{"on": "2026-08-30", "path": "a.py", "reason": "вчорашнє", "to": {"lines": 120}}]
    offenders = MODULE.raises_without_a_reason(_doc(100), _doc(150, stale))
    assert offenders and "100→150" in offenders[0]


def test_a_record_naming_another_ceiling_key_does_not_excuse_this_one() -> None:
    """Запис про рядки не є причиною для складності: ключі стелі незалежні."""
    named_lines = [{"on": "x", "path": "a.py", "reason": "r", "to": {"lines": 150}}]
    before = {"modules": {"a.py": {"lines": 100, "max_complexity": 5}}, "raised": []}
    after = {"modules": {"a.py": {"lines": 150, "max_complexity": 9}}, "raised": named_lines}
    offenders = MODULE.raises_without_a_reason(before, after)
    assert offenders and "max_complexity 5→9" in offenders[0]
    assert "lines" not in offenders[0]


def test_the_real_repository_has_no_unnamed_raise_against_head() -> None:
    """Стан самого репозиторію, а не синтетика: жодного неназваного підняття
    проти HEAD. Це і є база, від якої гейт рахує."""
    before = MODULE._at("HEAD")
    assert before, "module-budget.json недоступний у HEAD — порівняння не відбулось"
    import json

    after = json.loads((MODULE.ROOT / MODULE.BUDGET).read_text(encoding="utf-8"))
    assert MODULE.raises_without_a_reason(before, after) == []


def test_a_record_that_names_its_metric_beside_a_plain_number_counts() -> None:
    """Форма `{"metric": "lines", "to": 147}` не розпізнавалась ЖОДНИМ рядком.

    `remember` вимагав, щоб `to` був словником, тож сумлінний запис із метрикою поруч
    існував у реєстрі, читався людиною як названа причина — і не рахувався. Докстрінг
    при цьому обіцяв, що лишаються всі шість форм. Виміряно 06.09.2026: саме цією
    формою записана остання дюжина підняттів.
    """
    named = MODULE._recorded_raises(
        {"raised": [{"path": "a.py", "metric": "lines", "from": 10, "to": 12}]}
    )
    assert named == {"a.py": {("lines", 12)}}


def test_a_number_beside_a_metric_that_is_not_a_ceiling_names_nothing() -> None:
    """Інакше будь-яке число під будь-яким ключем зараховувало б будь-яке підняття."""
    assert MODULE._recorded_raises({"raised": [{"path": "c.py", "metric": "щось", "to": 9}]}) == {}
    assert (
        MODULE._recorded_raises({"raised": [{"path": "c.py", "metric": "lines", "to": True}]}) == {}
    )


def test_the_dict_form_still_counts_after_the_scalar_form_was_added() -> None:
    named = MODULE._recorded_raises({"raised": [{"path": "b.py", "to": {"lines": 5}}]})
    assert named == {"b.py": {("lines", 5)}}
