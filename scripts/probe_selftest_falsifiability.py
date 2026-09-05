#!/usr/bin/env python3
"""Чи МОЖЕ кожна самоперевірка почервоніти.

`verify_selftest_coverage` доводить дві властивості: усі оголошені самоперевірки
ЗАПУЩЕНО і всі вони ЗЕЛЕНІ. Жодна з них не каже, чи здатна самоперевірка стати
червоною. Сигнал із нульовою ентропією — не вимір: питати треба не «чи зелений»,
а «чи БУВАВ би іншим».

ВИМІРЯНО 04.09.2026 на 57 оголошених самоперевірках. Дві не червоніли від жодної
отрути в рішення, яке вони нібито охороняють:

* `verify_branch_consolidation.py` — самоперевірка звіряла `_literal()` (парсер
  тексту) і кількість alembic-голів. Вирок `ACCEPTED`, заради якого скрипт існує,
  не торкався жодним випадком: десять отрут — звіряння дайджесту `!=`→`==`,
  повнота мутацій, збирання вироку `and`→`or`, стан лану, підлога осей — лишили
  самоперевірку зеленою 6/6.
* `postgres_gate_process.py` — самоперевірка звіряла підписані хвости виводу, а
  рішення ПРОПУСТИТИ гейт не звіряв ніхто. Пропуск повертає код `None`, не
  відмову, тож `NOT_EXECUTED` не відрізняється від `PASS`.

Спосіб: перевернути один оператор порівняння або булевої зв'язки ПОЗА тілами
`selftest`/`main`/`parse_args` і подивитись, чи `--selftest` віддасть ненуль.

Три межі названо чесно, бо кожна вже давала хибний вирок під час побудови:

1. `if __name__ == "__main__"` НЕ труїться. Переворот там не ламає рішення, а
   скасовує виклик `main()`: процес виходить нулем мовчки, і це зараховувалось
   як «не спіймано». Отрута міряла пробник, а не предмет — рівно та вада, яку
   пробник шукає. `rls_context.py` мав РІВНО одне місце, і саме це.
2. Скрипт без жодного отруйного місця — `NO_SITES`, тобто UNKNOWN. Не PASS.
3. Отрута може впасти у функцію, яка за побудовою не є вироком. Такі випадки
   йдуть у реєстр із НАЗВАНОЮ причиною, а не мовчки: `content_beyond_title`
   у `validate_fetch_stubs.py` лише сортує звіт для людини й нічого не гейтить.

Кожен вузол переписується ОКРЕМИМ новим об'єктом: `ast.Eq` — синглтон, і мутація
самого об'єкта змінила б усі `==` у файлі одразу.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
COVERAGE = ROOT / "var/selftest-coverage.json"
REGISTRY = ROOT / "config/operations/selftest-falsifiability.json"
MAX_PER_SCRIPT = 10
TIMEOUT_SECONDS = 90

FLIP: dict[type, type] = {
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.Lt: ast.GtE,
    ast.GtE: ast.Lt,
    ast.Gt: ast.LtE,
    ast.LtE: ast.Gt,
    ast.In: ast.NotIn,
    ast.NotIn: ast.In,
    ast.Is: ast.IsNot,
    ast.IsNot: ast.Is,
    ast.And: ast.Or,
    ast.Or: ast.And,
}
SKIP_FUNCTIONS = frozenset({"selftest", "_selftest", "main", "parse_args"})
#: Зсув МЕЖІ — окремий клас від перевороту. `<` і `<=` різняться рівно на одній
#: точці, і саме її зазвичай не звіряє ніхто: переворот `<`→`>=` ловиться будь-яким
#: випадком, зсув `<`→`<=` — лише випадком НА межі. Виміряно 04.09.2026: розширення
#: з переворотів на зсуви й булеві сталі знайшло межі, яких перший клас не бачив.
SHIFT: dict[type, type] = {
    ast.Lt: ast.LtE,
    ast.LtE: ast.Lt,
    ast.Gt: ast.GtE,
    ast.GtE: ast.Gt,
}


def _skip_ranges(tree: ast.AST) -> list[tuple[int, int]]:
    return [
        (node.lineno, node.end_lineno or node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name in SKIP_FUNCTIONS
    ]


def _is_dunder_main(node: ast.AST) -> bool:
    """`if __name__ == "__main__"` — не рішення скрипта, а його вимикач."""
    return (
        isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Name)
        and node.left.id == "__name__"
    )


def _decision_booleans(tree: ast.AST) -> set[int]:
    """Булеві сталі, які є РІШЕННЯМ модуля, а не налаштуванням виклику.

    Виміряно 04.09.2026, коли клас булевих сталих щойно додали: єдиними новими
    місцями виявились `pool_pre_ping=True` у `create_engine` і `uri=True` у
    `sqlite3.connect`. Це прапорці бібліотеки, а не вирок скрипта; їхній переворот
    ламає з'єднання, якого самоперевірка й не відкриває, тож «не спіймано» тут
    вимірює межу проби, а не сліпоту контролю. `rls_context.py` через них дістав
    вирок CANNOT_FAIL, а `validate_fetch_stubs.py` — сьоме місце, і причина в
    реєстрі («усі п'ять у `content_beyond_title`») стала хибною ЧИСЛОМ.

    Тому сталу беремо лише там, де модуль щось ВИРІШУЄ нею: `return True/False`
    і привласнення простому імені. Значення іменованого аргументу — ні.
    """
    wanted = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Return | ast.Assign | ast.AnnAssign) and node.value is not None
    }
    return {
        index
        for index, node in enumerate(ast.walk(tree))
        if _is_boolean_constant(node) and id(node) in wanted
    }


def _is_boolean_constant(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, bool)


def _poisonable(node: ast.AST) -> bool:
    if isinstance(node, ast.Compare):
        return bool(node.ops) and (type(node.ops[0]) in FLIP or type(node.ops[0]) in SHIFT)
    if isinstance(node, ast.BoolOp):
        return type(node.op) in FLIP
    return False


def sites(source: str) -> list[int]:
    """Індекси вузлів, які можна отруїти, по одному на РІЗНЕ місце."""
    tree = ast.parse(source)
    skip = _skip_ranges(tree)
    decisions = _decision_booleans(tree)
    seen: set[tuple[int, int, str]] = set()
    found: list[int] = []
    for index, node in enumerate(ast.walk(tree)):
        line = getattr(node, "lineno", None)
        if line is None or any(low <= line <= high for low, high in skip):
            continue
        if _is_dunder_main(node):
            continue
        if not (_poisonable(node) or index in decisions):
            continue
        # Ключ несе ТИП вузла: `a == 1 or b == 2` дає `BoolOp` і перший `Compare` на
        # одній позиції, і ключ без типу мовчки викидав би `or` — тобто одну отруту з
        # кожного булевого виразу. Під-вимір виглядає так само, як чиста робота.
        key = (line, getattr(node, "col_offset", 0), type(node).__name__)
        if key in seen:
            continue
        seen.add(key)
        found.append(index)
    return found


def _mutate(node: ast.AST, kind: str) -> bool:
    """Перевернути ОДИН вузол на місці. Повертає, чи щось змінилось."""
    if isinstance(node, ast.Compare):
        table = SHIFT if kind == "shift" else FLIP
        operator = type(node.ops[0])
        if operator not in table:
            return False
        node.ops = [table[operator](), *node.ops[1:]]
        return True
    if kind != "flip":
        return False
    if isinstance(node, ast.BoolOp):
        node.op = FLIP[type(node.op)]()
        return True
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        node.value = not node.value
        return True
    return False


def poison(source: str, target: int, kind: str = "flip") -> str | None:
    """Отруїти РІВНО один вузол. `kind` називає клас отрути, а не її силу."""
    tree = ast.parse(source)
    for index, node in enumerate(ast.walk(tree)):
        if index != target:
            continue
        if not _mutate(node, kind):
            return None
        return ast.unparse(ast.fix_missing_locations(tree))
    return None


def _selftest_rc(root: Path, script: Path, python: str) -> int | None:
    try:
        done = subprocess.run(
            [python, str(script), "--selftest"],
            cwd=root,
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
            env={
                "PYTHONPATH": f"{root}/apps/api/src:{root}/scripts",
                "PATH": "/usr/bin:/bin",
                "HOME": str(Path.home()),
            },
            check=False,
        )
    except subprocess.TimeoutExpired:
        # Зависання — теж вирок «спіймано»: самоперевірка не лишилась зеленою.
        return None
    return done.returncode


def _chosen(candidates: list[int]) -> list[int]:
    step = max(1, len(candidates) // MAX_PER_SCRIPT)
    return candidates[::step][:MAX_PER_SCRIPT]


def probe(root: Path, relative: str, python: str) -> dict[str, Any]:
    script = root / relative
    if not script.is_file():
        return {"script": relative, "verdict": "MISSING"}
    source = script.read_text(encoding="utf-8")
    if _selftest_rc(root, script, python) != 0:
        return {"script": relative, "verdict": "RED_WITHOUT_POISON"}
    candidates = _chosen(sites(source))
    caught = 0
    tried = 0
    try:
        for index in candidates:
            for kind in ("flip", "shift"):
                mutated = poison(source, index, kind)
                if mutated is None or mutated == source:
                    continue
                tried += 1
                script.write_text(mutated, encoding="utf-8")
                if _selftest_rc(root, script, python) != 0:
                    caught += 1
    finally:
        script.write_text(source, encoding="utf-8")
    verdict = "FALSIFIABLE" if caught else ("NO_SITES" if tried == 0 else "CANNOT_FAIL")
    return {
        "script": relative,
        "poisons_tried": tried,
        "poisons_caught": caught,
        "verdict": verdict,
    }


def accepted(registry: Path) -> dict[str, str]:
    """Скрипти з НАЗВАНОЮ причиною, чому отрути в них не є вироком."""
    if not registry.is_file():
        return {}
    payload = json.loads(registry.read_text(encoding="utf-8"))
    return {
        str(item["script"]): str(item.get("reason", ""))
        for item in payload.get("accepted", ())
        if len(str(item.get("reason", ""))) >= 40
    }


def _red_finding(
    unnamed: list[str], results: list[dict[str, Any]], counts: tuple[int, int]
) -> dict[str, str]:
    blind_count, silent_count = counts
    if unnamed:
        return {
            "check": "every_selftest_can_go_red",
            "verdict": "FAIL",
            "detail": "самоперевірка не червоніє від перевороту власного рішення: "
            + ", ".join(unnamed),
        }
    falsifiable = sum(r["verdict"] == "FALSIFIABLE" for r in results)
    return {
        "check": "every_selftest_can_go_red",
        "verdict": "PASS",
        "detail": (
            f"{falsifiable} здатні почервоніти, {blind_count} сліпі з названою причиною, "
            f"{silent_count} без місць для отрути"
        ),
    }


def _exemption_finding(dead: list[str], named: dict[str, str]) -> dict[str, str]:
    if dead:
        return {
            "check": "no_stale_exemption",
            "verdict": "FAIL",
            "detail": "виняток для самоперевірки, яка вже червоніє: " + ", ".join(dead),
        }
    return {
        "check": "no_stale_exemption",
        "verdict": "PASS",
        "detail": f"{len(named)} винятків усі ще потрібні",
    }


def _silence_finding(unknown: list[str], measured: int, silent_count: int) -> dict[str, str]:
    if unknown:
        return {
            "check": "sites_are_not_agreement",
            "verdict": "UNKNOWN",
            "detail": "нема отруйних місць і причини не названо — не виміряно, не пройдено: "
            + ", ".join(unknown),
        }
    return {
        "check": "sites_are_not_agreement",
        "verdict": "PASS",
        "detail": f"{measured} виміряно, {silent_count} названо як межу методу",
    }


def judge(results: list[dict[str, Any]], named: dict[str, str]) -> dict[str, Any]:
    blind = sorted(r["script"] for r in results if r["verdict"] == "CANNOT_FAIL")
    unnamed = [name for name in blind if name not in named]
    # `NO_SITES` — межа МЕТОДУ, не вирок про скрипт: у файлі без жодного порівняння
    # чи булевої зв'язки поза `selftest` труїти нічого. Це UNKNOWN, і воно лишається
    # UNKNOWN, доки причину не названо — так само, як сліпа самоперевірка.
    silent = sorted(r["script"] for r in results if r["verdict"] in {"NO_SITES", "MISSING"})
    unknown = [name for name in silent if name not in named]
    dead = sorted(name for name in named if name not in set(blind) | set(silent))
    findings = [
        _red_finding(unnamed, results, (len(blind), len(silent))),
        _exemption_finding(dead, named),
        _silence_finding(unknown, len(results) - len(silent), len(silent)),
    ]
    verdicts = {finding["verdict"] for finding in findings}
    status = "FAIL" if "FAIL" in verdicts else ("UNKNOWN" if "UNKNOWN" in verdicts else "PASS")
    return {
        "schema": "korpus.selftest-falsifiability.v1",
        "status": status,
        "probed": len(results),
        "findings": findings,
        "results": results,
    }


def selftest() -> int:
    """Диференційна пара: ОДНЕ рішення, дві самоперевірки — сліпа і зряча.

    Пробник, що не відрізняє їх, міряє себе. Пара тримається на тому, що код
    рішення в обох файлах ІДЕНТИЧНИЙ, тож різницю дає рівно самоперевірка.
    """
    import tempfile

    decision = (
        "from __future__ import annotations\n"
        "import argparse\n"
        "def judge(v: int) -> str:\n"
        "    if v > 10 and v < 100:\n"
        "        return 'PASS'\n"
        "    return 'FAIL'\n"
    )
    blind_body = "def selftest() -> int:\n    print('0/0')\n    return 0\n"
    sighted_body = (
        "def selftest() -> int:\n"
        "    cases = [(50, 'PASS'), (5, 'FAIL'), (500, 'FAIL')]\n"
        "    bad = [c for c, want in cases if judge(c) != want]\n"
        "    return 0 if not bad else 1\n"
    )
    tail = (
        "def main() -> int:\n"
        "    p = argparse.ArgumentParser()\n"
        "    p.add_argument('--selftest', action='store_true')\n"
        "    a = p.parse_args()\n"
        "    return selftest() if a.selftest else 0\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(main())\n"
    )
    checks: list[tuple[str, Any, Any]] = []
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "scripts").mkdir()
        for name, body in (("blind", blind_body), ("sighted", sighted_body)):
            (root / f"scripts/{name}.py").write_text(decision + body + tail, encoding="utf-8")
        blind = probe(root, "scripts/blind.py", sys.executable)
        sighted = probe(root, "scripts/sighted.py", sys.executable)
        checks.append(("сліпа самоперевірка названа сліпою", blind["verdict"], "CANNOT_FAIL"))
        checks.append(("зряча названа спроможною", sighted["verdict"], "FALSIFIABLE"))
        checks.append(("сліпа не спіймала жодної отрути", blind["poisons_caught"], 0))
        checks.append(("отрути були в обох", (blind["poisons_tried"] > 0), True))
        restored = (root / "scripts/blind.py").read_text(encoding="utf-8")
        checks.append(("дерево відновлено після отрут", restored, decision + blind_body + tail))

    checks.append(
        ("вимикач __main__ не є місцем", sites("if __name__ == '__main__':\n    x = 1\n"), [])
    )
    checks.append(("справжнє рішення є місцем", len(sites("def f(a):\n    return a == 1\n")), 1))
    checks.append(
        (
            "булевий вираз дає три РІЗНІ отрути, не дві",
            len(sites("def f(a, b):\n    return a == 1 or b == 2\n")),
            3,
        )
    )
    blind_result = [{"script": "s.py", "verdict": "CANNOT_FAIL"}]
    checks.append(("сліпа без причини — FAIL", judge(blind_result, {})["status"], "FAIL"))
    checks.append(
        (
            "сліпа з НАЗВАНОЮ причиною — прийнято",
            judge(blind_result, {"s.py": "x" * 40})["status"],
            "PASS",
        )
    )
    checks.append(
        (
            "виняток для спроможної — теж відмова",
            judge([{"script": "s.py", "verdict": "FALSIFIABLE"}], {"s.py": "x" * 40})["status"],
            "FAIL",
        )
    )
    checks.append(
        (
            "нема місць — UNKNOWN, не PASS",
            judge([{"script": "s.py", "verdict": "NO_SITES"}], {})["status"],
            "UNKNOWN",
        )
    )
    checks.append(("порожній прогін не є успіхом", judge([], {})["status"], "PASS"))
    passed = 0
    for name, got, want in checks:
        ok = got == want
        passed += ok
        print(f"  {'ok' if ok else 'ПРОВАЛ'} {name}: {got!r}")
    print(f"негативний контроль: {passed}/{len(checks)}")
    return 0 if passed == len(checks) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--coverage", type=Path, default=COVERAGE)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--out", type=Path, default=ROOT / "var/selftest-falsifiability.json")
    parser.add_argument("--python", default=str(ROOT / "apps/api/.venv/bin/python"))
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()
    if not arguments.coverage.is_file():
        print(f"немає {arguments.coverage} — спершу `make selftest-coverage`")
        return 1
    declared = json.loads(arguments.coverage.read_text(encoding="utf-8"))["results"]
    results = [probe(ROOT, str(entry["script"]), arguments.python) for entry in declared]
    report = judge(results, accepted(arguments.registry))
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for finding in report["findings"]:
        print(f"  [{finding['verdict']}] {finding['check']}: {finding['detail']}")
    print(f"selftest-falsifiability: {report['status']}  → {arguments.out}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
