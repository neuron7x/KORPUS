#!/usr/bin/env python3
"""A ceiling on module size and function complexity that can only move down.

`TECHNICAL_DEBT_V5.md` asked for "decomposition of the large SQL repository and
security configuration validator". Decomposition on its own is not the property worth
having — a file split into three files nobody can hold in their head is the same debt
in more places. The property worth having is that the largest thing keeps getting
smaller, and that nothing grows past where it is today without someone deciding to.

So this is a ratchet, not a target. The budget records today's measurements; a module
may shrink freely, and any growth fails. Lowering the recorded ceiling is a deliberate
edit to `config/operations/module-budget.json`, which is what makes a reduction visible
in review rather than absorbed silently.

Cyclomatic complexity is counted structurally — branch points plus one — over ast, not
via an external tool, for the same reason every other check here avoids one: a gate
that needs an install step is a gate that gets skipped in the environment where it
matters. The absolute number is not comparable to another tool's; what it has to do is
be comparable to yesterday's run of this one.

New modules get a default ceiling rather than being unmeasured, because "not yet in the
budget" is how a file gets to be two thousand lines without anyone noticing.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUDGET = ROOT / "config/operations/module-budget.json"
SOURCES = ("apps/api/src/korpus", "scripts")
DEFAULT_LINES = 400
DEFAULT_COMPLEXITY = 15

BRANCHING = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.ExceptHandler,
    ast.With,
    ast.AsyncWith,
    ast.Assert,
    ast.BoolOp,
    ast.IfExp,
    ast.comprehension,
)


def complexity(node: ast.AST) -> int:
    return 1 + sum(isinstance(child, BRANCHING) for child in ast.walk(node))


def measure() -> dict[str, dict[str, object]]:
    measurements: dict[str, dict[str, object]] = {}
    for source in SOURCES:
        for path in sorted((ROOT / source).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text)
            functions = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            ]
            worst = max(((complexity(f), f.name) for f in functions), default=(0, "-"))
            measurements[str(path.relative_to(ROOT))] = {
                "lines": len(text.splitlines()),
                "max_complexity": worst[0],
                "worst_function": worst[1],
            }
    return measurements


def main() -> int:
    measurements = measure()
    budget = (
        json.loads(BUDGET.read_text(encoding="utf-8"))["modules"] if BUDGET.is_file() else {}
    )

    violations: list[str] = []
    for path, measured in sorted(measurements.items()):
        ceiling = budget.get(path, {"lines": DEFAULT_LINES, "max_complexity": DEFAULT_COMPLEXITY})
        if int(measured["lines"]) > int(ceiling["lines"]):
            violations.append(
                f"{path}: {measured['lines']} lines exceeds the recorded ceiling "
                f"{ceiling['lines']}"
            )
        if int(measured["max_complexity"]) > int(ceiling["max_complexity"]):
            violations.append(
                f"{path}: {measured['worst_function']} has complexity "
                f"{measured['max_complexity']}, above the recorded ceiling "
                f"{ceiling['max_complexity']}"
            )

    # A module that shrank is reported so the reduction can be written into the budget
    # deliberately. Lowering it automatically would let an accidental deletion freeze a
    # ceiling nobody chose.
    improvements = [
        f"{path}: now {measured['lines']} lines / complexity {measured['max_complexity']} "
        f"against a ceiling of {budget[path]['lines']} / {budget[path]['max_complexity']}"
        for path, measured in sorted(measurements.items())
        if path in budget
        and (
            int(measured["lines"]) < int(budget[path]["lines"])
            or int(measured["max_complexity"]) < int(budget[path]["max_complexity"])
        )
    ]

    report = {
        "status": "FAIL" if violations else "PASS",
        "modules": len(measurements),
        "unbudgeted": sorted(set(measurements) - set(budget)),
        "violations": violations,
        "improvements_to_record": improvements[:20],
        "largest": sorted(
            (
                {"path": path, **measured}
                for path, measured in measurements.items()
            ),
            key=lambda item: int(item["lines"]),
            reverse=True,
        )[:5],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
