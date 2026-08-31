#!/usr/bin/env python3
"""Червоне, яке прийняли, мусить мати стелю — інакше воно просто червоне.

Частина гейтів міряє не дерево, а РОЗГОРТАННЯ: обслуговуваний корпус, його журнал,
його прольоти. Вони не можуть стояти в `make check`, бо той мусить проходити там, де
ні корпусу, ні сервісу немає, — і саме тому вони не стояли ніде. `span-hygiene` був
червоний ще до 31.08.2026 і не червонив нічого.

Підключити його як є означало б зробити щоденний гейт червоним для всіх; лишити
мовчки означає вдавати, що діри немає. Третій стан: борг ПРИЙНЯТИЙ, названий і має
СТЕЛЮ, а гейт відмовляє на погіршенні.

    гірше за стелю   → FAIL, із числом і різницею
    рівно стеля      → PASS
    краще за стелю   → PASS, і стелю треба ЗНИЗИТИ — гейт каже, на скільки

Останнє важливе: ратчет, який не помічає покращення, з часом перетворюється на
дозвіл. Тому поліпшення тут не мовчазне — воно вимагає запису, як і підняття.

    check_deployment_debt.py
    check_deployment_debt.py --selftest
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "config/operations/deployment-debt.json"
SCHEMA = "korpus.deployment-debt.v1"


def metric_at(report: dict[str, Any], path: str) -> int | None:
    """Число за шляхом виду `spans_dirty` або `by_kind.chrome`.

    `None` — не «нуль», а «не виміряно»: звіт без цього поля нічого не доводить, і
    зарахувати його в нуль означало б оголосити борг закритим тим, що його не міряли.
    """
    node: Any = report
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, int) and not isinstance(node, bool) else None


def judge(entry: dict[str, Any], report: dict[str, Any] | None) -> dict[str, Any]:
    target = str(entry.get("target", "?"))
    ceiling = entry.get("ceiling")
    if report is None:
        return {"target": target, "verdict": "UNKNOWN", "detail": "звіт не прочитано"}
    if not isinstance(ceiling, int):
        return {"target": target, "verdict": "FAIL", "detail": "стеля не є цілим числом"}
    measured = metric_at(report, str(entry.get("metric", "")))
    if measured is None:
        return {
            "target": target,
            "verdict": "UNKNOWN",
            "detail": f"метрику {entry.get('metric')!r} у звіті не знайдено",
        }
    if measured > ceiling:
        return {
            "target": target,
            "verdict": "FAIL",
            "measured": measured,
            "ceiling": ceiling,
            "detail": f"погіршення: {measured} проти стелі {ceiling} (+{measured - ceiling})",
        }
    if measured < ceiling:
        return {
            "target": target,
            "verdict": "PASS",
            "measured": measured,
            "ceiling": ceiling,
            "detail": f"покращення: {measured} проти {ceiling} — стелю треба знизити до {measured}",
            "lower_ceiling_to": measured,
        }
    return {
        "target": target,
        "verdict": "PASS",
        "measured": measured,
        "ceiling": ceiling,
        "detail": f"на стелі: {measured}",
    }


def verdict(results: list[dict[str, Any]]) -> str:
    if not results:
        return "UNKNOWN"
    verdicts = {item["verdict"] for item in results}
    if "FAIL" in verdicts:
        return "FAIL"
    return "UNKNOWN" if "UNKNOWN" in verdicts else "PASS"


def run_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    """Виконати гейт і взяти його звіт. Ненульовий код — очікуваний: борг же прийнятий."""
    command = entry.get("command")
    if not isinstance(command, list) or not command:
        return None
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    text = completed.stdout
    start = text.find("{")
    if start < 0:
        return None
    try:
        parsed = json.loads(text[start : text.rfind("}") + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def selftest() -> int:
    entry = {"target": "t", "metric": "spans_dirty", "ceiling": 89}
    cases: list[tuple[str, dict[str, Any] | None, str]] = [
        ("рівно на стелі", {"spans_dirty": 89}, "PASS"),
        ("краще за стелю", {"spans_dirty": 40}, "PASS"),
        ("гірше на одиницю", {"spans_dirty": 90}, "FAIL"),
        ("метрики у звіті немає — UNKNOWN, не PASS", {"other": 1}, "UNKNOWN"),
        ("звіт не прочитано — UNKNOWN, не PASS", None, "UNKNOWN"),
        ("булеве не є числом — UNKNOWN", {"spans_dirty": True}, "UNKNOWN"),
    ]
    bad = 0
    for name, report, expected in cases:
        got = judge(entry, report)["verdict"]
        ok = got == expected
        bad += not ok
        print(f"  [{'ok' if ok else 'ЗБІЙ'}] {name}: {got}")

    improved = judge(entry, {"spans_dirty": 40})
    ok = improved.get("lower_ceiling_to") == 40
    bad += not ok
    print(
        f"  [{'ok' if ok else 'ЗБІЙ'}] покращення називає нову стелю: {improved.get('lower_ceiling_to')}"
    )

    nested = judge(
        {"target": "t", "metric": "by_kind.chrome", "ceiling": 13}, {"by_kind": {"chrome": 13}}
    )
    ok = nested["verdict"] == "PASS"
    bad += not ok
    print(f"  [{'ok' if ok else 'ЗБІЙ'}] вкладена метрика читається: {nested['verdict']}")

    no_ceiling = judge({"target": "t", "metric": "x"}, {"x": 1})
    ok = no_ceiling["verdict"] == "FAIL"
    bad += not ok
    print(
        f"  [{'ok' if ok else 'ЗБІЙ'}] запис без стелі — відмова, не дозвіл: {no_ceiling['verdict']}"
    )

    total = len(cases) + 3
    print(f"\nнегативний контроль: {total - bad}/{total}")
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--out", type=Path, default=ROOT / "var/deployment-debt.json")
    parser.add_argument("--selftest", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()

    try:
        registry = json.loads(arguments.registry.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print(json.dumps({"schema": SCHEMA, "status": "UNKNOWN", "reason": "реєстр не прочитано"}))
        return 2
    entries = registry.get("accepted") if isinstance(registry, dict) else None
    if not isinstance(entries, list) or not entries:
        print(json.dumps({"schema": SCHEMA, "status": "UNKNOWN", "reason": "реєстр порожній"}))
        return 2

    results = [judge(entry, run_entry(entry)) for entry in entries]
    overall = verdict(results)
    report = {"schema": SCHEMA, "status": overall, "results": results}
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for item in results:
        print(f"  [{item['verdict']}] {item['target']}: {item['detail']}")
    print(f"\ndeployment-debt: {overall}  → {arguments.out}")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
