"""Стан, якого ніхто не обирав, виглядає однаково і як задум, і як недогляд.

27 із 35 таблиць бази порожні. Найбільша група — навчальний шар: 1516 рядків коду й 1036
рядків тестів, яких не імпортує жоден маршрут API. Виміряно графом імпортів 01.09.2026:
із восьми його модулів досяжні з API рівно ДВА, і обидва — самі означення таблиць
(`repository.py` тягне їх заради метаданих SQLAlchemy). Схема під'єднана, поведінка ні —
тому дванадцять таблиць створюються й ніхто в них не пише.

Тут перевіряється не сам шар, а ОГОЛОШЕННЯ про нього: воно мусить падати в ОБИДВА боки.
Гейт, що ловить лише пробудження, не помітить тихого видалення, і реєстр перетвориться
на опис неіснуючого.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from check_dormant_subsystems import (  # noqa: E402
    import_graph,
    judge,
    reachable_from_api,
)

REGISTRY = {"subsystems": {"s": {"modules_unreachable_from_api": ["m.a", "m.b"]}}}
BOTH = {"m.a", "m.b"}


def test_a_declared_dormant_subsystem_that_stayed_asleep_passes() -> None:
    verdict = judge(REGISTRY, set(), {"s": {"t": 0}}, BOTH)

    assert verdict["rate"] == 1.0
    assert verdict["detail"][0]["state"] == "DORMANT"


def test_a_module_wired_into_the_api_wakes_the_subsystem() -> None:
    """Під'єднання — рішення, і воно має бути ухвалене, а не помічене згодом."""
    verdict = judge(REGISTRY, {"m.b"}, {"s": {"t": 0}}, BOTH)

    assert verdict["detail"][0]["modules_now_reachable"] == ["m.b"]
    assert verdict["rate"] == 0.0


def test_a_row_in_a_table_declared_empty_is_a_change() -> None:
    """Порожня таблиця — твердження; рядок у ній означає, що хтось туди пише."""
    assert judge(REGISTRY, set(), {"s": {"t": 3}}, BOTH)["detail"][0]["tables_with_rows"] == ["t"]


def test_a_table_that_disappeared_is_a_change_too() -> None:
    """None — не нуль: відсутня таблиця й порожня таблиця це різні світи."""
    assert judge(REGISTRY, set(), {"s": {"t": None}}, BOTH)["detail"][0]["tables_absent"] == ["t"]


def test_a_module_that_vanished_is_a_change() -> None:
    """Другий бік. Реєстр, що переживає власний предмет, описує неіснуюче."""
    verdict = judge(REGISTRY, set(), {"s": {"t": 0}}, {"m.a"})

    assert verdict["detail"][0]["modules_that_vanished"] == ["m.b"]
    assert verdict["rate"] == 0.0


def test_the_import_graph_keeps_the_edge_a_package_import_hides(tmp_path: Path) -> None:
    """`from korpus.infrastructure import learning_schema` дає module без імені модуля.

    Перша версія цього виміру губила саме таке ребро й оголосила досяжний модуль
    недосяжним. Тест пінить ребро, а не число.
    """
    source = tmp_path / "src"
    (source / "korpus" / "api").mkdir(parents=True)
    (source / "korpus" / "infrastructure").mkdir(parents=True)
    (source / "korpus" / "__init__.py").write_text("", encoding="utf-8")
    (source / "korpus" / "api" / "__init__.py").write_text("", encoding="utf-8")
    (source / "korpus" / "api" / "routes.py").write_text(
        "from korpus.infrastructure import repository\n", encoding="utf-8"
    )
    (source / "korpus" / "infrastructure" / "__init__.py").write_text("", encoding="utf-8")
    (source / "korpus" / "infrastructure" / "repository.py").write_text(
        "from korpus.infrastructure import learning_schema  # noqa: F401\n", encoding="utf-8"
    )
    (source / "korpus" / "infrastructure" / "learning_schema.py").write_text("", encoding="utf-8")

    graph = import_graph(source)
    reachable = reachable_from_api(graph)

    assert "korpus.infrastructure.learning_schema" in reachable


def test_a_module_nothing_imports_is_not_reachable(tmp_path: Path) -> None:
    """Негативний контроль: граф, у якому досяжне все, нічого не міряє."""
    source = tmp_path / "src"
    (source / "korpus" / "api").mkdir(parents=True)
    (source / "korpus" / "api" / "routes.py").write_text("", encoding="utf-8")
    (source / "korpus" / "orphan.py").write_text("", encoding="utf-8")

    assert "korpus.orphan" not in reachable_from_api(import_graph(source))


def test_the_real_learning_layer_is_still_asleep() -> None:
    """Твердження про ЦЕ дерево, не про вигаданий граф."""
    graph = import_graph(ROOT / "apps/api/src")
    reachable = reachable_from_api(graph)

    assert "korpus.domain.learning" not in reachable
    assert "korpus.infrastructure.learning_repository" not in reachable
    # Схема — досяжна, і саме тому таблиці існують. Це не суперечність, а розділення.
    assert "korpus.infrastructure.learning_schema" in reachable


def test_the_registry_names_only_modules_that_exist() -> None:
    """Реєстр, що згадує неіснуюче, помітно розходиться з деревом ще до прогону."""
    import json

    registry = json.loads(
        (ROOT / "config/operations/dormant-subsystems.json").read_text(encoding="utf-8")
    )
    graph = import_graph(ROOT / "apps/api/src")
    named = [
        module
        for spec in registry["subsystems"].values()
        for key in ("modules_unreachable_from_api", "modules_reachable_as_schema_only")
        for module in spec.get(key, [])
    ]

    assert named, "реєстр без модулів нічого не оголошує"
    assert [module for module in named if module not in graph] == []


def test_the_measurer_parses_this_repository_without_error() -> None:
    """Модуль із синтаксичною помилкою не сміє тихо випасти з графа."""
    unparsed = []
    for path in (ROOT / "apps/api/src").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            unparsed.append(str(path.relative_to(ROOT)))

    assert unparsed == []
