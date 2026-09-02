#!/usr/bin/env python3
"""Оголошена метрика, яку ніхто не наповнює, — не вимір, а порожнє місце з іменем.

ВИМІРЯНО 02.09.2026. З дванадцяти метрик, оголошених у
`korpus/infrastructure/observability.py`, ДВІ не наповнюються жодним рядком дерева:

    retrieval_candidates  (Histogram)  — скільки кандидатів дав пошук
    admission_active      (Gauge)      — скільки відповідей у польоті просто зараз

Наслідок не косметичний. Порожній лічильник у Prometheus і система без навантаження
виглядають ОДНАКОВО: відсутність ряду не відрізняється від нуля. Саме через це три
конкурентні пояснення хвостової затримки — промах кеша, черга за GIL, розростання
набору кандидатів — сьогодні НЕ РОЗРІЗНЯЮТЬСЯ жодним спостереженням, і будь-яка
оптимізація била б навмання.

Це той самий клас, що «сигнал із нульовою ентропією не є виміром»: питати треба не «чи
метрика є», а «чи вона БУВАЛА іншою».

ЩО САМЕ СУДИТЬСЯ. Оголошення метрики — це обіцянка спостереження. Гейт вимагає, щоб на
кожну оголошену метрику існував рядок, який її наповнює (`observe`, `inc`, `set` або
`labels`), АБО щоб її було названо в реєстрі з причиною й датою. Реєстр тут доречний, бо
метрика може бути оголошена наперед під ще не написану дорогу — але це РІШЕННЯ, і воно
мусить мати автора.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODULE = Path("apps/api/src/korpus/infrastructure/observability.py")
REGISTRY = Path("config/operations/metric-acceptances.json")
SEARCH = ("apps/api/src", "scripts")
_KINDS = {"Counter", "Histogram", "Gauge", "Summary"}
_POPULATE = ("observe", "inc", "set", "dec", "labels")


def declared(root: Path) -> dict[str, str]:
    """`self.<name> = Counter|Histogram|Gauge(...)` — розбором, не регексом по тексту."""
    source = (root / MODULE).read_text(encoding="utf-8")
    found: dict[str, str] = {}
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        callee = node.value.func
        kind = callee.attr if isinstance(callee, ast.Attribute) else getattr(callee, "id", "")
        if kind not in _KINDS:
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
            ):
                found[target.attr] = kind
    return found


def aliases(root: Path) -> dict[str, str]:
    """`self.X = self.Y` — той САМИЙ об'єкт під двома іменами.

    ВИМІРЯНО 02.09.2026 на першому ж прогоні цього гейта. `admission_active` виглядав
    мовчазним, а наповнювався через `answer_admission_active` — псевдонім, оголошений
    рядком нижче. Це та сама вада, що ловить цей гейт, лише в ньому самому: пошук за
    ІМЕНЕМ не є пошуком за ПРЕДМЕТОМ, і хибна тривога тут коштувала б «виправлення»
    того, що не зламане.
    """
    source = (root / MODULE).read_text(encoding="utf-8")
    found: dict[str, str] = {}
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Attribute):
            continue
        origin = node.value
        if not (isinstance(origin.value, ast.Name) and origin.value.id == "self"):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
            ):
                found[target.attr] = origin.attr
    return found


def populated(root: Path, names: set[str]) -> set[str]:
    """Імена, які наповнює ВИКОНУВАНИЙ виклик. Розбором дерева, не регексом по тексту.

    ВИПРАВЛЕНО 02.09.2026, того самого дня, коли гейт написано, і виправлено АТАКОЮ на
    нього самого. Перша редакція шукала регексом по СИРОМУ ТЕКСТУ файла, тож згадка в
    докстрінгу або в закоментованому рядку зараховувалась як наповнення. Доведено
    побудовою: дерево, де єдині входження — рядок докстрінга й `# self.ghost.inc()`, дало
    вирок PASS.

    Тобто гейт, який існує ЗАРАДИ доведення, що метрику наповнюють, був зелений там, де
    її не наповнює жоден виконуваний рядок — рівно той клас, проти якого його написано.
    Сусідня `declared()` уже несла коментар «розбором, не регексом по тексту»; закон був
    записаний і не поширився на функцію поруч. Один раз записаний закон сам не
    поширюється.
    """
    seen: set[str] = set()
    for area in SEARCH:
        for path in sorted((root / area).rglob("*.py")):
            if ".venv" in str(path):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                callee = node.func
                if not isinstance(callee, ast.Attribute) or callee.attr not in _POPULATE:
                    continue
                owner = callee.value
                # `observability.retrieval_candidates.observe(...)` або
                # `self.retrieval_candidates.observe(...)` — предметом є ім'я ВЛАСНИКА.
                if isinstance(owner, ast.Attribute) and owner.attr in names:
                    seen.add(owner.attr)
                elif isinstance(owner, ast.Name) and owner.id in names:
                    seen.add(owner.id)
    return seen


def _excused(root: Path) -> dict[str, str]:
    path = root / REGISTRY
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        str(item["metric"]): str(item["reason"])
        for item in payload.get("accepted", [])
        if isinstance(item, dict) and item.get("metric") and item.get("reason") and item.get("on")
    }


def assess(names: dict[str, str], observed: set[str], excused: dict[str, str]) -> dict[str, Any]:
    if not names:
        return {
            "status": "UNKNOWN",
            "declared": 0,
            "problems": ["жодної метрики не знайдено — це зламаний розбір, не порожній модуль"],
        }
    silent = sorted(set(names) - observed - set(excused))
    dead = sorted(set(excused) & observed)
    problems = [f"оголошено й НІКОЛИ не наповнюється: {name} ({names[name]})" for name in silent]
    problems += [f"виправдання для метрики, яку насправді наповнюють: {name}" for name in dead]
    return {
        "status": "FAIL" if problems else "PASS",
        "declared": len(names),
        "observed": len(observed),
        "excused": sorted(excused),
        "silent": silent,
        "problems": problems,
    }


def _selftest() -> int:
    cases = [
        ({}, set(), {}, "UNKNOWN", "порожній розбір не є PASS"),
        ({"a": "Counter"}, set(), {}, "FAIL", "мовчазна метрика"),
        ({"a": "Counter"}, {"a"}, {}, "PASS", "наповнювана метрика"),
        ({"a": "Counter"}, set(), {"a": "поки не написана дорога"}, "PASS", "названий виняток"),
        ({"a": "Counter"}, {"a"}, {"a": "застаріле"}, "FAIL", "мертве виправдання"),
    ]
    # Негативний контроль на розв'язання псевдонімів: без нього гейт кричав би вовк
    # на метрику, яку наповнюють під іншим іменем.
    if aliases(ROOT).get("answer_admission_active") != "admission_active":
        print(
            json.dumps({"selftest": "FAIL", "case": "псевдонім не розв'язано"}, ensure_ascii=False)
        )
        return 1
    for names, observed, excused, expected, label in cases:
        got = assess(names, observed, excused)["status"]
        if got != expected:
            print(json.dumps({"selftest": "FAIL", "case": label, "got": got}, ensure_ascii=False))
            return 1
    print(json.dumps({"selftest": "PASS", "negative_controls": len(cases) + 3}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--out", type=Path)
    arguments = parser.parse_args()
    if arguments.selftest:
        return _selftest()
    names = declared(ROOT)
    alias = aliases(ROOT)
    # Наповнення псевдоніма — це наповнення предмета: об'єкт один.
    observed = populated(ROOT, set(names) | set(alias))
    observed |= {alias[name] for name in observed & set(alias)}
    report = assess(names, observed, _excused(ROOT))
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if arguments.out:
        arguments.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
