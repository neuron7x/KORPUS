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
from typing import TypedDict

ROOT = Path(__file__).resolve().parents[1]
BUDGET = ROOT / "config/operations/module-budget.json"
SOURCES = ("apps/api/src/korpus", "scripts")
DEFAULT_LINES = 400
DEFAULT_COMPLEXITY = 15
DEFAULT_FUNCTION_LINES = 60
DEFAULT_FUNCTION_ARGS = 8
DEFAULT_NESTING = 4
DEFAULT_PROOF_LINES = 220

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


class Shape(TypedDict):
    """One module's measured shape. Typed so the ratchet cannot compare object to int."""

    lines: int
    proof_lines: int
    max_complexity: int
    worst_function: str
    max_function_lines: int
    longest_function: str
    max_function_args: int
    widest_function: str
    max_nesting: int
    deepest_function: str


#: A negative control is not code that grew — it is a proof that grew. Measured 2026-08-29:
#: a parallel session extended one selftest from 27 probes to 36, closing six mutants, and
#: this ratchet went red for it. A metric that pushes against adding negative controls is
#: pushing against the only thing that shows a gate can fail: a gate run on correct data
#: cannot prove it catches incorrect data, so the synthetic violations in a selftest are
#: where it is checked at all. Their lines are counted separately and bounded separately.
#: The separation is bounded, or it is a hole: a function called `selftest` would be an
#: unmeasured room to hide real logic in. Two conditions, both required. The name is one.
#: The other is that the module actually runs it — a module that never dispatches on
#: `--selftest` has no self-test, whatever it named the function, and every line is
#: ordinary code again. And what passes both is still bounded, by its own ceiling below.
PROOF_FUNCTIONS = ("selftest", "_selftest", "self_test")
PROOF_DISPATCH = "--selftest"


def _is_proof(node: ast.FunctionDef | ast.AsyncFunctionDef, *, dispatches: bool) -> bool:
    return dispatches and node.name in PROOF_FUNCTIONS


def measure() -> dict[str, Shape]:
    measurements: dict[str, Shape] = {}
    for source in SOURCES:
        for path in sorted((ROOT / source).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text)
            all_functions = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            ]
            dispatches = PROOF_DISPATCH in text
            proofs = [n for n in all_functions if _is_proof(n, dispatches=dispatches)]
            functions = [n for n in all_functions if not _is_proof(n, dispatches=dispatches)]
            proof_lines = sum(function_lines(node) for node in proofs)
            worst = max(((complexity(f), f.name) for f in functions), default=(0, "-"))
            longest = max(((function_lines(f), f.name) for f in functions), default=(0, "-"))
            widest = max(((parameter_count(f), f.name) for f in functions), default=(0, "-"))
            deepest = max(((nesting_depth(f), f.name) for f in functions), default=(0, "-"))
            measurements[str(path.relative_to(ROOT))] = {
                # Proof lines are subtracted: the ceiling bounds the program, and a
                # selftest that doubles is a gate that got harder to fool, not a module
                # that got harder to read.
                "lines": len(text.splitlines()) - proof_lines,
                "proof_lines": proof_lines,
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


def shape_violations(path: str, measured: Shape, ceiling: dict[str, object]) -> list[str]:
    reported = []
    for key, name_key, default, shape in SHAPES:
        limit = _as_int(ceiling.get(key, default), default)
        value = int(measured[key])  # type: ignore[literal-required]
        if value > limit:
            name = measured[name_key]  # type: ignore[literal-required]
            reported.append(
                f"{path}: {name} has {shape} {value}, above the recorded ceiling {limit}"
            )
    return reported


def _as_int(value: object, fallback: int) -> int:
    """A recorded ceiling is JSON, so it is `object` until something narrows it.

    A ceiling that is not a number is a corrupt budget entry, not a licence to skip the
    check: falling back to the default keeps it running and keeps it strict. Measured
    2026-08-29: with `int()` here instead, `"lines": "999999"` disabled the line ratchet for
    that module and reported PASS with zero violations.
    """
    return value if isinstance(value, int) and not isinstance(value, bool) else fallback


DEFAULT_CEILING = {
    "lines": DEFAULT_LINES,
    "max_complexity": DEFAULT_COMPLEXITY,
    "max_function_lines": DEFAULT_FUNCTION_LINES,
    "max_function_args": DEFAULT_FUNCTION_ARGS,
    "max_nesting": DEFAULT_NESTING,
}


#: Мінімальна довжина причини звільнення. Порожній рядок і «-» — це не пояснення, а
#: заповнювач; поріг низький навмисно, бо ловить він саме заповнювач, а не короткість.
MIN_EXEMPTION_REASON = 20


def _exemption_problems(path: str, ceiling: dict[str, object]) -> list[str]:
    """Звільнення без записаної причини не є звільненням.

    `"lines": null` знімає стелю рядків з файлу назавжди, і воно виглядає точно так само,
    як звільнення, про яке хтось подумав, і як звільнення, що з'явилось під час
    механічної синхронізації чисел. Різницю несе лише текст поруч. Виявлено 2026-08-30:
    скрипт, що піднімав стелі за виміром, ледь не підставив число замість `null` —
    свідоме рішення зникло б без сліду, і гейт лишався б зеленим. Тепер осиротіле
    звільнення падає тут, а не тихо перетворюється на звичайну стелю.
    """
    exempt = [key for key in ("lines", "max_complexity") if key in ceiling and ceiling[key] is None]
    if not exempt:
        return []
    reason = ceiling.get("reason")
    if isinstance(reason, str) and len(reason.strip()) >= MIN_EXEMPTION_REASON:
        return []
    return [
        f"{path}: {sorted(exempt)} звільнено від стелі без записаної причини — звільнення "
        "без пояснення не відрізнити від такого, що з'явилось випадково"
    ]


def module_violations(path: str, measured: Shape, ceiling: dict[str, object]) -> list[str]:
    """Every ceiling one module is held to. Extracted when the ratchet caught its own
    growth: `main` went to 81 lines and complexity 14 under the proof-line separation.
    The recorded number is the thing the ratchet defends, so the fix is the extraction,
    never the number — that is what the ceiling is for."""
    found: list[str] = _exemption_problems(path, ceiling)
    # A registry — the mutant catalogue, a rule table — grows every time the system
    # gains a check, which is to say every time it gets better. A line ceiling there
    # penalises the behaviour the ratchet exists to encourage. The exemption is
    # `"lines": null`, and it is per-file with a reason recorded beside it, because
    # a blanket exemption is how a ratchet stops holding anything. Complexity is
    # never exempt: a registry that grew a branch is no longer a registry.
    # int() of a JSON value parses "999999" happily. `_as_int` was added for the three
    # shape keys and these two were left on int(), so a string line ceiling lifted the
    # ratchet entirely while a string shape ceiling fell back to the default. The guard
    # belongs on every ceiling read, not on the ones that were already integers.
    line_ceiling = ceiling["lines"]
    if line_ceiling is not None:
        limit = _as_int(line_ceiling, DEFAULT_LINES)
        if int(measured["lines"]) > limit:
            found.append(f"{path}: {measured['lines']} lines exceeds the recorded ceiling {limit}")
    proof_limit = _as_int(ceiling.get("proof_lines", DEFAULT_PROOF_LINES), DEFAULT_PROOF_LINES)
    if int(measured["proof_lines"]) > proof_limit:
        found.append(
            f"{path}: {measured['proof_lines']} self-test lines exceed the recorded "
            f"ceiling {proof_limit} — proofs are exempt from the module ceiling, "
            "not from every ceiling"
        )
    if int(measured["max_complexity"]) > _as_int(ceiling["max_complexity"], DEFAULT_COMPLEXITY):
        found.append(
            f"{path}: {measured['worst_function']} has complexity "
            f"{measured['max_complexity']}, above the recorded ceiling "
            f"{ceiling['max_complexity']}"
        )
    found.extend(shape_violations(path, measured, ceiling))
    return found


def main() -> int:
    measurements = measure()
    budget = json.loads(BUDGET.read_text(encoding="utf-8"))["modules"] if BUDGET.is_file() else {}

    violations: list[str] = []
    for path, measured in sorted(measurements.items()):
        violations.extend(module_violations(path, measured, budget.get(path, DEFAULT_CEILING)))

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
                and int(measured["lines"]) < _as_int(budget[path]["lines"], DEFAULT_LINES)
            )
            or int(measured["max_complexity"])
            < _as_int(budget[path]["max_complexity"], DEFAULT_COMPLEXITY)
        )
    ]

    report = {
        "status": "FAIL" if violations else "PASS",
        "modules": len(measurements),
        "unbudgeted": sorted(set(measurements) - set(budget)),
        "violations": violations,
        "improvements_to_record": improvements[:20],
        "largest": [
            {"path": path, **measurements[path]}
            for path in sorted(
                measurements, key=lambda name: measurements[name]["lines"], reverse=True
            )[:5]
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
