#!/usr/bin/env python3
"""Ратчет прийнятого боргу розгортання."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "config/operations/deployment-debt.json"
SCHEMA = "korpus.deployment-debt.v1"


def metric_at(report: dict[str, Any], path: str, kind: str = "number") -> int | None:
    node: Any = report
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    if kind == "length":
        return len(node) if isinstance(node, list) else None
    return node if isinstance(node, int) and not isinstance(node, bool) else None


def judge(entry: dict[str, Any], report: dict[str, Any] | None) -> dict[str, Any]:
    target = str(entry.get("target", "?"))
    ceiling = entry.get("ceiling")
    if report is None:
        return {"target": target, "verdict": "UNKNOWN", "detail": "звіт не прочитано"}
    if not isinstance(ceiling, int):
        return {"target": target, "verdict": "FAIL", "detail": "стеля не є цілим числом"}
    measured = metric_at(
        report, str(entry.get("metric", "")), str(entry.get("metric_kind", "number"))
    )
    if measured is None:
        detail = f"метрику {entry.get('metric')!r} у звіті не знайдено"
        return {"target": target, "verdict": "UNKNOWN", "detail": detail}
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


def resolve_command(value: object, runtime_root: Path | None = None) -> list[str] | None:
    if not isinstance(value, list) or not value or not all(isinstance(part, str) for part in value):
        return None
    command = list(value)
    command = _bind_runtime_root(command, runtime_root)
    if command is None:
        return None
    if command[0] == "{python}":
        command[0] = sys.executable
    if command[0] == "make" and not any(part.startswith("PY=") for part in command[1:]):
        command.append(f"PY={shlex.quote(sys.executable)}")
    return command


def _bind_runtime_root(command: list[str], runtime_root: Path | None) -> list[str] | None:
    if runtime_root is None:
        return None if any("{runtime_root}" in part for part in command) else command
    return [part.replace("{runtime_root}", str(runtime_root)) for part in command]


def run_entry(entry: dict[str, Any], runtime_root: Path | None = None) -> dict[str, Any] | None:
    command = resolve_command(entry.get("command"), runtime_root)
    if command is None:
        return None
    try:
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    except OSError:
        return None
    text = completed.stdout
    start = text.find("{")
    if start < 0:
        return None
    try:
        parsed = json.loads(text[start : text.rfind("}") + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def declared_runtime_root() -> Path | None:
    try:
        state = ROOT / "config/operations/canonical-state.json"
        value = json.loads(state.read_text(encoding="utf-8"))["canonical_root"]
    except (OSError, json.JSONDecodeError, KeyError):
        return None
    return Path(value) if isinstance(value, str) and value else None


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

    length_entry = {"target": "t", "metric": "failures", "metric_kind": "length", "ceiling": 2}
    for name, report, expected in (
        ("перелік відмов рахується довжиною", {"failures": ["a", "b"]}, "PASS"),
        ("на одну відмову більше — стеля пробита", {"failures": ["a", "b", "c"]}, "FAIL"),
        ("перелік не список — UNKNOWN, не нуль", {"failures": 2}, "UNKNOWN"),
    ):
        got = judge(length_entry, report)["verdict"]
        ok = got == expected
        bad += not ok
        print(f"  [{'ok' if ok else 'ЗБІЙ'}] {name}: {got}")

    numeric_on_a_list = judge({"target": "t", "metric": "failures", "ceiling": 2}, {"failures": []})
    ok = numeric_on_a_list["verdict"] == "UNKNOWN"
    bad += not ok
    print(
        f"  [{'ok' if ok else 'ЗБІЙ'}] без metric_kind перелік НЕ читається як число: "
        f"{numeric_on_a_list['verdict']}"
    )

    no_ceiling = judge({"target": "t", "metric": "x"}, {"x": 1})
    ok = no_ceiling["verdict"] == "FAIL"
    bad += not ok
    print(
        f"  [{'ok' if ok else 'ЗБІЙ'}] запис без стелі — відмова, не дозвіл: {no_ceiling['verdict']}"
    )

    total = len(cases) + 7
    print(f"\nнегативний контроль: {total - bad}/{total}")
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--out", type=Path, default=ROOT / "var/deployment-debt.json")
    parser.add_argument("--runtime-root", type=Path, default=declared_runtime_root())
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

    results = [judge(entry, run_entry(entry, arguments.runtime_root)) for entry in entries]
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
