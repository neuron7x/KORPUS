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

Four shapes are measured, not one. Module lines and worst-function complexity were here
first; function length, parameter count and nesting depth were added after an external
audit found `create_app` at 251 lines and `execute_hybrid_search_impl` at 24 parameters —
both inside modules that were comfortably under their recorded line ceiling, which is
exactly how a module budget alone lets a single function grow without limit. A ceiling on
the file says nothing about the function, and the function is what a reader has to hold.
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
DEFAULT_FUNCTION_LINES = 60
DEFAULT_FUNCTION_ARGS = 8
DEFAULT_NESTING = 4

# Only statements that indent their body count toward depth. A nested function or class
# starts its own frame and is measured separately, so a module of small closures does not
# read as one deeply nested function.
NESTING = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try)

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


def nesting_depth(node: ast.AST, depth: int = 0) -> int:
    deepest = depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        inner = depth + 1 if isinstance(child, NESTING) else depth
        deepest = max(deepest, nesting_depth(child, inner))
    return deepest


def parameter_count(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    args = node.args
    named = len(args.posonlyargs) + len(args.args) + len(args.kwonlyargs)
    return named + (1 if args.vararg else 0) + (1 if args.kwarg else 0)


def function_lines(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    return (node.end_lineno or node.lineno) - node.lineno + 1


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
            longest = max(((function_lines(f), f.name) for f in functions), default=(0, "-"))
            widest = max(((parameter_count(f), f.name) for f in functions), default=(0, "-"))
            deepest = max(((nesting_depth(f), f.name) for f in functions), default=(0, "-"))
            measurements[str(path.relative_to(ROOT))] = {
                "lines": len(text.splitlines()),
                "max_complexity": worst[0],
                "worst_function": worst[1],
                "max_function_lines": longest[0],
                "longest_function": longest[1],
                "max_function_args": widest[0],
                "widest_function": widest[1],
                "max_nesting": deepest[0],
                "deepest_function": deepest[1],
            }
    return measurements


# A module can sit far under its line ceiling while one function inside it holds most of
# those lines. These three read the function, not the file: measured value, the name to
# report, the budget key, the default when a module has no recorded ceiling, and the word
# the message uses.
SHAPES = (
    ("max_function_lines", "longest_function", DEFAULT_FUNCTION_LINES, "lines"),
    ("max_function_args", "widest_function", DEFAULT_FUNCTION_ARGS, "parameters"),
    ("max_nesting", "deepest_function", DEFAULT_NESTING, "nesting depth"),
)


def shape_violations(
    path: str, measured: dict[str, object], ceiling: dict[str, object]
) -> list[str]:
    reported = []
    for key, name_key, default, shape in SHAPES:
        limit = int(ceiling.get(key, default))  # type: ignore[arg-type]
        if int(measured[key]) > limit:  # type: ignore[call-overload]
            reported.append(
                f"{path}: {measured[name_key]} has {shape} {measured[key]}, "
                f"above the recorded ceiling {limit}"
            )
    return reported


def main() -> int:
    measurements = measure()
    budget = json.loads(BUDGET.read_text(encoding="utf-8"))["modules"] if BUDGET.is_file() else {}

    violations: list[str] = []
    for path, measured in sorted(measurements.items()):
        ceiling = budget.get(
            path,
            {
                "lines": DEFAULT_LINES,
                "max_complexity": DEFAULT_COMPLEXITY,
                "max_function_lines": DEFAULT_FUNCTION_LINES,
                "max_function_args": DEFAULT_FUNCTION_ARGS,
                "max_nesting": DEFAULT_NESTING,
            },
        )
        # A registry — the mutant catalogue, a rule table — grows every time the system
        # gains a check, which is to say every time it gets better. A line ceiling there
        # penalises the behaviour the ratchet exists to encourage. The exemption is
        # `"lines": null`, and it is per-file with a reason recorded beside it, because
        # a blanket exemption is how a ratchet stops holding anything. Complexity is
        # never exempt: a registry that grew a branch is no longer a registry.
        if ceiling["lines"] is not None and int(measured["lines"]) > int(ceiling["lines"]):
            violations.append(
                f"{path}: {measured['lines']} lines exceeds the recorded ceiling {ceiling['lines']}"
            )
        if int(measured["max_complexity"]) > int(ceiling["max_complexity"]):
            violations.append(
                f"{path}: {measured['worst_function']} has complexity "
                f"{measured['max_complexity']}, above the recorded ceiling "
                f"{ceiling['max_complexity']}"
            )
        violations.extend(shape_violations(path, measured, ceiling))

    # A module that shrank is reported so the reduction can be written into the budget
    # deliberately. Lowering it automatically would let an accidental deletion freeze a
    # ceiling nobody chose.
    improvements = [
        f"{path}: now {measured['lines']} lines / complexity {measured['max_complexity']} "
        f"against a ceiling of {budget[path]['lines']} / {budget[path]['max_complexity']}"
        for path, measured in sorted(measurements.items())
        if path in budget
        and (
            (
                budget[path]["lines"] is not None
                and int(measured["lines"]) < int(budget[path]["lines"])
            )
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
            ({"path": path, **measured} for path, measured in measurements.items()),
            key=lambda item: int(item["lines"]),
            reverse=True,
        )[:5],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
