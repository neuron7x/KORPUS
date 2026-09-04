#!/usr/bin/env python3
"""Підсистеми, які СПЛЯТЬ — оголошено, а не залишено без нагляду.

27 із 35 таблиць бази порожні в обох базах доказів, і найбільша група — навчальний шар:
1516 рядків коду й 1036 рядків тестів, які не імпортує жоден маршрут API. Це не вада
сама по собі: підсистема може чекати свого часу. Вадою є те, що стан НІХТО НЕ ОБИРАВ —
він виглядає однаково і як задум, і як недогляд, і жодне число про нього не говорить.

## Що саме тут вирішується

Виміряно графом імпортів, не на око. Із 297 модулів застосунку 177 досяжні з
`korpus.api.*`/`korpus.main`. Із восьми навчальних досяжні ДВА, і обидва — лише
означення таблиць: `repository.py` тягне їх заради метаданих SQLAlchemy, щоб DDL знав
про таблиці. Тобто СХЕМА під'єднана, ПОВЕДІНКА ні — саме тому дванадцять таблиць
створюються й ніхто в них не пише.

## Форма гейта

Оголошення несе два перевірювані твердження, і кожне падає окремо:
  · названі модулі НЕДОСЯЖНІ з API — якщо хтось їх під'єднав, підсистема прокинулась,
    і це рішення, яке має бути ухвалене, а не помічене згодом;
  · названі таблиці ПОРОЖНІ — якщо в них з'явився рядок, у них хтось пише.

Перелік модулів теж звіряється: підсистема, що виросла новим модулем, більше не та,
яку оголошували. Мовчазне «і ще один файл» — це те, як сплячий шар прокидається
непоміченим.

Обидва напрямки навмисно: гейт, який ловить лише пробудження, не помітить, що
підсистему тихо ВИДАЛИЛИ, і реєстр перетвориться на опис неіснуючого.

    check_dormant_subsystems.py [--database DB]
    check_dormant_subsystems.py --selftest
"""

from __future__ import annotations

import argparse
import ast
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "apps/api/src"
REGISTRY = ROOT / "config/operations/dormant-subsystems.json"
DEFAULT_DB = ROOT / "var/runtime/corpus-v6-20260807/korpus.db"
SCRIPTS = ROOT / "scripts"

#: Точки входу, які запускає розгортання, крім API: юніт `korpus-worker.service` кличе
#: `python -m korpus.cli worker-loop`, а MCP подається окремим процесом. Досяжність
#: САМЕ з API — вужча міра, ніж «продакшен це виконує», і саме тому вона тут не одна.
RUNTIME_ROOTS = (
    "korpus.cli",
    "korpus.worker_service",
    "korpus.mcp.stdio",
    "korpus.mcp.server",
)


def _edges_of(node: ast.AST, modules: dict[str, Path]) -> set[str]:
    """Ребра одного вузла — винесено, щоб гілка ПАКЕТНОГО імпорту читалась окремо."""
    if isinstance(node, ast.Import):
        return {alias.name for alias in node.names if alias.name.startswith("korpus")}
    if not isinstance(node, ast.ImportFrom):
        return set()
    if not node.module or not node.module.startswith("korpus"):
        return set()
    # `from korpus.infrastructure import learning_schema` дає `node.module` БЕЗ імені
    # модуля. Перша версія губила саме це ребро й оголосила досяжний модуль недосяжним.
    children = {f"{node.module}.{alias.name}" for alias in node.names}
    return {node.module} | (children & set(modules))


def import_graph(source: Path) -> dict[str, set[str]]:
    """Ребра імпортів усередині `korpus`.

    `from korpus.infrastructure import learning_schema` дає `node.module` без імені
    модуля, тож дочірнє ребро додається окремо — перша версія цього виміру його губила
    й оголосила досяжний модуль недосяжним.
    """
    modules = {
        ".".join(path.relative_to(source).with_suffix("").parts): path
        for path in source.rglob("*.py")
        if "__pycache__" not in path.parts
    }
    graph: dict[str, set[str]] = {}
    for name, path in modules.items():
        edges: set[str] = set()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            graph[name] = edges
            continue
        for node in ast.walk(tree):
            edges.update(_edges_of(node, modules))
        graph[name] = edges
    return graph


def reachable_from_api(graph: dict[str, set[str]]) -> set[str]:
    roots = [name for name in graph if name.startswith("korpus.api.") or name == "korpus.main"]
    seen, queue = set(roots), list(roots)
    while queue:
        for nxt in graph.get(queue.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def script_seeds(scripts: Path, modules: set[str]) -> set[str]:
    """Модулі, які імпортують гейти й інструменти релізу.

    Це ДРУГА поверхня продакшену. Скрипт — теж виконуваний шлях: `provenance`,
    `production_hard_predicates`, `recovery` недосяжні з API й при цьому щодня
    виконуються ланом. Без цієї поверхні «недосяжний з API» назвав би сплячим те,
    що працює.
    """
    found: set[str] = set()
    for path in sorted(scripts.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            found |= _edges_of(node, {name: path for name in modules})
    return found & modules


def closure(graph: dict[str, set[str]], roots: set[str]) -> set[str]:
    seen = {root for root in roots if root in graph}
    queue = list(seen)
    while queue:
        for nxt in graph.get(queue.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def reachable_from_production(graph: dict[str, set[str]], scripts: Path) -> set[str]:
    """Усе, що досягає ХОЧ ОДНА поверхня продакшену: API, рантайм-юніти, гейти."""
    api = {name for name in graph if name.startswith("korpus.api.") or name == "korpus.main"}
    return (
        closure(graph, api)
        | closure(graph, set(RUNTIME_ROOTS))
        | closure(graph, script_seeds(scripts, set(graph)))
    )


def behavioural(module: str) -> bool:
    """`__init__` пакета — простір імен, не поведінка: він не «спить», його нема кому будити."""
    return not module.endswith(".__init__") and module != "korpus"


def table_rows(database: Path, tables: list[str]) -> dict[str, int | None]:
    """None означає «таблиці немає» — це не нуль і не рядок, а відсутність предмета."""
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        present = {
            str(row[0])
            for row in connection.execute("select name from sqlite_master where type='table'")
        }
        counts: dict[str, int | None] = {}
        for table in tables:
            counts[table] = (
                int(connection.execute(f'select count(*) from "{table}"').fetchone()[0])
                if table in present
                else None
            )
        return counts
    finally:
        connection.close()


def judge(
    registry: dict[str, Any],
    reachable: set[str],
    counts: dict[str, dict[str, int | None]],
    every_module: set[str],
    production_reachable: set[str] | None = None,
) -> dict[str, Any]:
    """Вирок про оголошені підсистеми ПЛЮС виявлення повз реєстр.

    Доти гейт питав лише те, що хтось уже згадав оголосити: він звіряв ВЛАСНЕ
    оголошення й був зелений рівно в тому стані, заради якого існує. Виміряно
    04.09.2026 на цьому дереві: реєстр називав 2 підсистеми й 9 модулів, а
    недосяжними з усіх поверхонь продакшену були 40 модулів. Вирок читався
    `rate 1.0, still_dormant 2` — і мовчав про 33 модулі та 3344 рядки.

    `production_reachable=None` означає, що виявлення НЕ проводилось, і звіт каже
    про це `null`, а не порожній перелік: невиміряне не є порожнім.
    """
    findings: list[dict[str, Any]] = []
    for name, spec in sorted(registry["subsystems"].items()):
        declared = sorted(spec.get("modules_unreachable_from_api", []))
        woke = sorted(module for module in declared if module in reachable)
        gone = sorted(module for module in declared if module not in every_module)
        written = sorted(
            table for table, rows in counts.get(name, {}).items() if rows not in (0, None)
        )
        absent = sorted(table for table, rows in counts.get(name, {}).items() if rows is None)
        problems = {
            "modules_now_reachable": woke,
            "modules_that_vanished": gone,
            "tables_with_rows": written,
            "tables_absent": absent,
        }
        findings.append(
            {
                "subsystem": name,
                "state": "DORMANT" if not any(problems.values()) else "CHANGED",
                "declared_modules": len(declared),
                "declared_tables": len(counts.get(name, {})),
                **problems,
            }
        )
    dormant = sum(1 for item in findings if item["state"] == "DORMANT")
    all_declared = {
        module
        for spec in registry["subsystems"].values()
        for key in ("modules_unreachable_from_api", "modules_reachable_as_schema_only")
        for module in spec.get(key, [])
    }
    undeclared: list[str] | None = None
    if production_reachable is not None:
        undeclared = sorted(
            module
            for module in every_module - production_reachable
            if behavioural(module) and module not in all_declared
        )
    changed = [item["subsystem"] for item in findings if item["state"] == "CHANGED"]
    if undeclared is None:
        status = "UNKNOWN"
    elif undeclared:
        status = "UNDECLARED_DORMANT"
    elif changed:
        status = "CHANGED"
    else:
        status = "MEASURED"
    return {
        "schema": "korpus.dormant-subsystems.v2",
        "subsystems": len(findings),
        "still_dormant": dormant,
        "changed": changed,
        "rate": round(dormant / len(findings), 4) if findings else None,
        "declared_modules_total": len(all_declared),
        "undeclared_dormant": undeclared,
        "undeclared_dormant_count": None if undeclared is None else len(undeclared),
        "status": status,
        "detail": findings,
    }


def selftest() -> int:
    """Негативні контролі: реєстр без гейта — це опис, а не рішення."""
    both = {"m.a", "m.b"}
    registry = {"subsystems": {"s": {"modules_unreachable_from_api": ["m.a", "m.b"]}}}
    checks: list[tuple[str, Any, Any]] = []

    quiet = judge(registry, set(), {"s": {"t": 0}}, both)
    checks.append(("сплячий шар — DORMANT", quiet["detail"][0]["state"], "DORMANT"))
    checks.append(("сплячий дає 1.0", quiet["rate"], 1.0))

    awake = judge(registry, {"m.b"}, {"s": {"t": 0}}, both)
    checks.append(
        ("під'єднаний модуль видно", awake["detail"][0]["modules_now_reachable"], ["m.b"])
    )
    checks.append(("пробудження робить CHANGED", awake["detail"][0]["state"], "CHANGED"))
    checks.append(("пробудження знімає 1.0", awake["rate"], 0.0))

    written = judge(registry, set(), {"s": {"t": 3}}, both)
    checks.append(("рядок у таблиці видно", written["detail"][0]["tables_with_rows"], ["t"]))

    absent = judge(registry, set(), {"s": {"t": None}}, both)
    checks.append(("зникла таблиця — теж зміна", absent["detail"][0]["tables_absent"], ["t"]))

    vanished = judge(registry, set(), {"s": {"t": 0}}, {"m.a"})
    checks.append(("зниклий модуль видно", vanished["detail"][0]["modules_that_vanished"], ["m.b"]))

    # ── Виявлення повз реєстр. Без цих плечей гейт зелений рівно в тому стані,
    # заради якого існує: він звіряє власне оголошення.
    three = {"m.a", "m.b", "m.c"}
    hidden = judge(registry, set(), {"s": {"t": 0}}, three, production_reachable=set())
    checks.append(("неоголошений сплячий ВИДНО", hidden["undeclared_dormant"], ["m.c"]))
    checks.append(("він робить вирок не MEASURED", hidden["status"], "UNDECLARED_DORMANT"))
    checks.append(("оголошені при цьому досі сплять", hidden["still_dormant"], 1))

    declared_all = {"subsystems": {"s": {"modules_unreachable_from_api": ["m.a", "m.b", "m.c"]}}}
    named = judge(declared_all, set(), {"s": {"t": 0}}, three, production_reachable=set())
    checks.append(("оголошення знімає скаргу", named["undeclared_dormant"], []))
    checks.append(("і повертає MEASURED", named["status"], "MEASURED"))

    served = judge(registry, set(), {"s": {"t": 0}}, three, production_reachable={"m.c"})
    checks.append(("досяжний із продакшену не сплячий", served["undeclared_dormant"], []))

    unmeasured = judge(registry, set(), {"s": {"t": 0}}, three)
    checks.append(("БЕЗ виявлення — null, не []", unmeasured["undeclared_dormant"], None))
    checks.append(("і вирок UNKNOWN, не MEASURED", unmeasured["status"], "UNKNOWN"))

    pkg = judge(
        registry,
        set(),
        {"s": {"t": 0}},
        {"m.a", "m.b", "korpus.mcp.__init__"},
        production_reachable=set(),
    )
    checks.append(("__init__ пакета не «спить»", pkg["undeclared_dormant"], []))

    awake_named = judge(registry, {"m.b"}, {"s": {"t": 0}}, both, production_reachable={"m.b"})
    checks.append(("пробудження лишається CHANGED", awake_named["status"], "CHANGED"))

    passed = 0
    for name, got, want in checks:
        ok = got == want
        passed += ok
        print(f"  {'ok' if ok else 'ПРОВАЛ'} {name}: {got!r}")
    print(f"негативний контроль: {passed}/{len(checks)}")
    return 0 if passed == len(checks) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=ROOT / "var/dormant-subsystems.json")
    parser.add_argument("--selftest", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()

    registry = json.loads(arguments.registry.read_text(encoding="utf-8"))
    graph = import_graph(SOURCE)
    reachable = reachable_from_api(graph)
    counts = {
        name: table_rows(arguments.database, list(spec.get("tables_expected_empty", [])))
        for name, spec in registry["subsystems"].items()
    }
    report = judge(
        registry,
        reachable,
        counts,
        set(graph),
        production_reachable=reachable_from_production(graph, SCRIPTS),
    )
    report["ran_at"] = datetime.now(UTC).isoformat()
    report["database"] = str(arguments.database)
    report["modules_reachable_from_api"] = len(reachable)
    report["modules_total"] = len(graph)
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    arguments.out.write_text(rendered, encoding="utf-8")
    print(rendered)
    # Три різні вироки, і жоден не є іншим: невиміряне не дорівнює порожньому,
    # а неоголошене не дорівнює пробудженому.
    return 0 if report["status"] == "MEASURED" else 1


if __name__ == "__main__":
    sys.exit(main())
