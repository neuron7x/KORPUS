#!/usr/bin/env python3
"""Знаменник доказової поверхні не сміє скорочуватись мовчки.

Виміряно 02.09.2026: прибрати вісь із `answer-axes.json` і прогнати `check_answer_axes` —
код виходу НУЛЬ. Знаменник 16 → 15, вирок зелений, і жодне число не сказало, що предмет
виміру став меншим. Так само нікого не обходить зникла ціль лану, зниклий гейт живучості
чи зниклий предикат готовності. Зелене від скорочення того, що міряють, — найтихіший
спосіб оголосити систему готовою.

ЧОМУ ІМЕНА, А НЕ ЛИШЕ ЛІЧИЛЬНИКИ

Лічильник ловить лише чисте скорочення. Прибрати одну вісь і додати іншу — і 16
лишається 16, хоча властивість, яку боронила прибрана, більше не міряє ніхто. Тому малі
виміри оголошуються ПОІМЕННО: зникнення конкретного члена видно попри будь-які додавання.

Великі виміри (мутанти, забюджетовані модулі, скрипти із самоперевіркою) оголошуються
кількістю з одностороннім ратчетом: перелічувати п'ятсот ідентифікаторів у конфізі —
друге оголошення того самого факту, і воно розійдеться мовчки. Там ловиться чисте
скорочення, і цього досить: додати мутанта, щоб приховати прибраного, дорожче, ніж
просто не прибирати.

ЗРОСТАННЯ — НЕ ПОМИЛКА, АЛЕ Й НЕ МОВЧАННЯ

Нові члени звітуються як `grown`, і `--record` вписує їх у декларацію. Автоматично, без
`--record`, декларація не рухається: інакше гейт сам собі підписував би нову поверхню.

ПРИБРАТИ МОЖНА — АЛЕ НАЗВАВШИ

Запис у `removed` вимагає `dimension`, `member`, `on` і `reason`. Це та сама дисципліна,
що в `module-budget.raised`: рішення лишається можливим, невидимим — ні.

    check_release_surface.py
    check_release_surface.py --record
    check_release_surface.py --selftest
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
SURFACE = ROOT / "config/operations/release-surface.json"

#: Виміри, оголошені ПОІМЕННО. Малі й такі, де зникнення одного члена є подією.
NAMED = ("answer_axes", "hard_predicates", "liveness_gates", "lane_validate_targets")
#: Виміри, оголошені кількістю з одностороннім ратчетом.
COUNTED = ("mutants", "budgeted_modules", "scripts_declaring_selftest", "liveness_poisons")


def _lane_targets(makefile: str, lane: str) -> list[str]:
    """Передумови ЗАГОЛОВКА плюс скрипти, які лан запускає у власному РЕЦЕПТІ.

    ВИМІРЯНО 02.09.2026. Перша версія читала лише заголовок правила, і три скрипти,
    які `validate` запускає прямо в рецепті — `validate_repository.py`,
    `validate_infrastructure.py`, `validate_kubernetes.py` — не входили в знаменник
    узагалі. Прибрати рядок із рецепта означало скоротити охоронювану поверхню, не
    зрушивши жодного числа: рівно та дірка, проти якої цей гейт існує.

    Скрипт рецепта і ціль-передумова — різні речі, тож і члени різні: `validate_x.py`
    поруч із `openapi`. Спільне в них те, що зникнення кожного мусить бути назване.
    """
    found = re.search(rf"^{re.escape(lane)}:([^=\n]*)$", makefile, re.M)
    if found is None:
        return []
    members = [item for item in found.group(1).split() if not item.startswith(("$", "#"))]
    body = makefile[found.end() :]
    recipe = body[: body.find("\n\n")] if "\n\n" in body else body
    members += re.findall(r"scripts/([a-z_0-9]+\.py)", recipe)
    return members


def observe(root: Path = ROOT) -> dict[str, Any]:
    """Поверхня, ЯКА Є. Читається з дерева, не з копії переліку."""
    axes = json.loads((root / "config/operations/answer-axes.json").read_text(encoding="utf-8"))
    predicates = json.loads(
        (root / "config/assurance/production-hard-predicates-v1.json").read_text(encoding="utf-8")
    )
    liveness = yaml.safe_load(
        (root / "config/operations/gate-liveness.yaml").read_text(encoding="utf-8")
    )
    makefile = (root / "Makefile").read_text(encoding="utf-8")
    catalogue = ast.parse((root / "scripts/run_mutation_tests.py").read_text(encoding="utf-8"))
    budget = json.loads((root / "config/operations/module-budget.json").read_text(encoding="utf-8"))
    declares = re.compile(r"""add_argument\(\s*["']--selftest["']""")
    return {
        "answer_axes": sorted(axes["axes"]),
        "hard_predicates": sorted(item["id"] for item in predicates["predicates"]),
        "liveness_gates": sorted(gate["name"] for gate in liveness["gates"]),
        "lane_validate_targets": sorted(_lane_targets(makefile, "validate")),
        "mutants": sum(
            1
            for node in ast.walk(catalogue)
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Mutant"
        ),
        "budgeted_modules": len(budget["modules"]),
        "liveness_poisons": sum(len(gate.get("poisons") or []) for gate in liveness["gates"]),
        "scripts_declaring_selftest": sum(
            1
            for path in sorted((root / "scripts").glob("*.py"))
            if declares.search(path.read_text(encoding="utf-8", errors="ignore"))
        ),
    }


def _excused(surface: dict[str, Any], dimension: str) -> set[str]:
    return {
        str(item.get("member"))
        for item in surface.get("removed", [])
        if item.get("dimension") == dimension
        and item.get("reason")
        and item.get("on")
        and item.get("member")
    }


def evaluate(surface: dict[str, Any], observed: dict[str, Any]) -> dict[str, Any]:
    declared = surface.get("dimensions", {})
    shrunk: list[str] = []
    grown: list[str] = []
    for dimension in NAMED:
        before = set(declared.get(dimension, {}).get("members", []))
        now = set(observed[dimension])
        gone = sorted(before - now - _excused(surface, dimension))
        shrunk += [f"{dimension}: зник {name!r} і це ніде не названо" for name in gone]
        grown += [f"{dimension}: додано {name!r}" for name in sorted(now - before)]
    for dimension in COUNTED:
        was = int(declared.get(dimension, {}).get("count", 0))
        count = int(observed[dimension])
        allowance = len(_excused(surface, dimension))
        if count + allowance < was:
            shrunk.append(f"{dimension}: {was} -> {count}, скорочення не названо")
        elif count > was:
            grown.append(f"{dimension}: {was} -> {count}")
    return {
        "status": "FAIL" if shrunk else "PASS",
        "shrunk": shrunk,
        "grown": grown,
        "dimensions": {
            name: (len(observed[name]) if name in NAMED else observed[name])
            for name in (*NAMED, *COUNTED)
        },
    }


def record(observed: dict[str, Any], surface: dict[str, Any]) -> dict[str, Any]:
    surface.setdefault("schema", "korpus.release-surface.v1")
    surface.setdefault("removed", [])
    dimensions = surface.setdefault("dimensions", {})
    for dimension in NAMED:
        dimensions.setdefault(dimension, {})["members"] = sorted(observed[dimension])
    for dimension in COUNTED:
        dimensions.setdefault(dimension, {})["count"] = int(observed[dimension])
    return surface


def selftest() -> int:
    """Обидва контролі: скорочення мусить червоніти, зростання — ні."""
    observed = {
        "answer_axes": ["a", "b"],
        "hard_predicates": ["p"],
        "liveness_gates": ["g"],
        "lane_validate_targets": ["t"],
        "mutants": 10,
        "budgeted_modules": 5,
        "liveness_poisons": 3,
        "scripts_declaring_selftest": 2,
    }
    full = record(dict(observed), {})
    if evaluate(full, observed)["status"] != "PASS":
        print("selftest FAIL: незмінена поверхня мусить бути PASS", file=sys.stderr)
        return 1

    shrunk = {**observed, "answer_axes": ["a"]}
    verdict = evaluate(full, shrunk)
    if verdict["status"] != "FAIL" or not verdict["shrunk"]:
        print("selftest FAIL: зникла вісь не почервоніла", file=sys.stderr)
        return 1

    swapped = {**observed, "answer_axes": ["a", "c"]}
    if evaluate(full, swapped)["status"] != "FAIL":
        print("selftest FAIL: заміна члена при тій самій кількості не помічена", file=sys.stderr)
        return 1

    fewer = {**observed, "mutants": 9}
    if evaluate(full, fewer)["status"] != "FAIL":
        print("selftest FAIL: скорочення лічильника не почервоніло", file=sys.stderr)
        return 1

    named = {
        **full,
        "removed": [
            {"dimension": "answer_axes", "member": "b", "on": "2026-01-01", "reason": "перевірка"}
        ],
    }
    if evaluate(named, shrunk)["status"] != "PASS":
        print("selftest FAIL: НАЗВАНЕ прибирання мусить проходити", file=sys.stderr)
        return 1

    silent = {**full, "removed": [{"dimension": "answer_axes", "member": "b"}]}
    if evaluate(silent, shrunk)["status"] != "FAIL":
        print("selftest FAIL: запис без причини й дати не є названим", file=sys.stderr)
        return 1

    more = {**observed, "answer_axes": ["a", "b", "c"], "mutants": 11}
    grown_verdict = evaluate(full, more)
    if grown_verdict["status"] != "PASS" or len(grown_verdict["grown"]) != 2:
        print("selftest FAIL: зростання мусить проходити й бути названим", file=sys.stderr)
        return 1

    print(json.dumps({"selftest": "PASS"}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    observed = observe()
    surface: dict[str, Any] = (
        json.loads(SURFACE.read_text(encoding="utf-8")) if SURFACE.is_file() else {}
    )
    if args.record:
        SURFACE.parent.mkdir(parents=True, exist_ok=True)
        SURFACE.write_text(
            json.dumps(record(observed, surface), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"recorded": True, "dimensions": len(surface["dimensions"])}))
        return 0
    verdict = evaluate(surface, observed)
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0 if verdict["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
