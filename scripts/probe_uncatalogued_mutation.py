#!/usr/bin/env python3
"""Sample ordinary mutations outside the curated catalogue.

A passing unmodified baseline and executed pytest failure distinguish a kill from
an execution failure. Incomplete measurements publish no kill-rate estimate.
The default sandbox and restoration guard prevent mutations reaching served code;
explicit in-place execution retains the historical lock and clean-tree contract.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mutation_probe_execution import SuiteExecution, mutation_outcome, run_suite

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "apps/api/src/korpus"
CATALOGUE = ROOT / "scripts/run_mutation_tests.py"
LOCK = ROOT / "var/mutation-probe.lock"

# Default isolation closes the historical SIGTERM defect: a killed probe once left
# a mutation in the tree imported by the live service. In-place mode is explicit.
DEFAULT_WORKSPACE = ROOT

COMPARISON_FLIP = {
    ast.Lt: ("<", ">="),
    ast.Gt: (">", "<="),
    ast.LtE: ("<=", ">"),
    ast.GtE: (">=", "<"),
    ast.Eq: ("==", "!="),
    ast.NotEq: ("!=", "=="),
    ast.Is: (" is ", " is not "),
    ast.IsNot: (" is not ", " is "),
    ast.In: (" in ", " not in "),
    ast.NotIn: (" not in ", " in "),
}


@dataclass(frozen=True)
class Seeded:
    module: str
    line: int
    kind: str
    old: str
    new: str


def catalogued_modules() -> set[str]:
    tree = ast.parse(CATALOGUE.read_text(encoding="utf-8"))
    files: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "Mutant"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            files.add(node.args[1].value)
    return files


def uncatalogued_modules(only: list[str] | None = None) -> list[str]:
    """Select uncatalogued source paths; unknown and catalogued are distinct states."""
    catalogued = catalogued_modules()
    modules = {
        str(path.relative_to(ROOT))
        for path in SOURCE_ROOT.rglob("*.py")
        if path.name != "__init__.py" and "__pycache__" not in path.parts
    }
    uncatalogued = modules - catalogued
    if only is None:
        return sorted(uncatalogued)
    requested = set(only)
    unknown = sorted(requested - modules)
    if unknown:
        raise SystemExit(f"названі шляхи не є модулями джерела: {unknown}")
    return sorted(requested & uncatalogued)


def seed_module(relative: str, workspace: Path) -> list[Seeded]:
    """One mutation per eligible source line, so a line is never sampled twice."""
    text = (workspace / relative).read_text(encoding="utf-8")
    lines = text.splitlines()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    seeded: dict[int, Seeded] = {}
    for node in ast.walk(tree):
        line = getattr(node, "lineno", None)
        if line is None or line in seeded or line > len(lines):
            continue
        source = lines[line - 1]
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            flip = COMPARISON_FLIP.get(type(node.ops[0]))
            if flip and flip[0] in source:
                seeded[line] = Seeded(relative, line, "comparison", flip[0], flip[1])
        elif isinstance(node, ast.BoolOp):
            operator, replacement = (
                (" and ", " or ") if isinstance(node.op, ast.And) else (" or ", " and ")
            )
            if operator in source:
                seeded[line] = Seeded(relative, line, "boolean", operator, replacement)
    return list(seeded.values())


def apply(mutant: Seeded, workspace: Path) -> str:
    path = workspace / mutant.module
    original = path.read_bytes().decode("utf-8")
    lines = original.splitlines(keepends=True)
    lines[mutant.line - 1] = lines[mutant.line - 1].replace(mutant.old, mutant.new, 1)
    path.write_text("".join(lines), encoding="utf-8")
    return original


def suite_kills(timeout_seconds: float, workspace: Path) -> SuiteExecution:
    """Return a bounded execution receipt; only the baseline can authorize a kill."""
    return run_suite(timeout_seconds, workspace)


def _lock_pid() -> int | None:
    try:
        text = LOCK.read_text(encoding="utf-8")
    except OSError:
        return None
    found = re.search(r"pid=(\d+)", text)
    return int(found.group(1)) if found else None


def _lock_holder_alive() -> bool:
    """An orphaned lock is observable; it cannot silently block all future probes."""
    pid = _lock_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def source_tree_is_clean() -> bool:
    listing = subprocess.run(
        ["git", "status", "--porcelain", "--", "apps/api/src", "scripts"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return listing.returncode == 0 and not listing.stdout.strip()


def wilson_interval(
    successes: int, total: int, z: float = 1.959963984540054
) -> tuple[float, float]:
    """Two-sided Wilson score interval; the same estimator the assurance layer uses."""
    if total <= 0:
        return 0.0, 1.0
    rate = successes / total
    denominator = 1.0 + z * z / total
    centre = (rate + z * z / (2 * total)) / denominator
    spread = z * math.sqrt(rate * (1.0 - rate) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, centre - spread), min(1.0, centre + spread)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=25)
    parser.add_argument("--seed", type=int, default=20260829)
    parser.add_argument("--timeout", type=float, default=420.0)
    parser.add_argument("--out", type=Path, default=ROOT / "var/uncatalogued-mutation-probe.json")
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="мутувати САМЕ ЦЕ дерево, а не копію; лише для налагодження — аварійний "
        "вихід лишає мутацію в дереві, з якого імпортує живий API",
    )
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument(
        "--paths",
        nargs="+",
        default=None,
        help="звузити предмет проби до названих модулів (шляхи від кореня дерева)",
    )
    args = parser.parse_args()

    if LOCK.exists():
        print(
            json.dumps(
                {
                    "status": "REFUSED",
                    "reason": f"another probe holds {LOCK.relative_to(ROOT)}",
                    "holder_pid": _lock_pid(),
                    "holder_alive": _lock_holder_alive(),
                    "orphaned": _lock_pid() is not None and not _lock_holder_alive(),
                    "note": (
                        "Осиротілий замок — ПОДІЯ, а не тиша: він означає, що попередній "
                        "прогін урвався, і дерево могло лишитись мутованим. Перевір "
                        "`git status` перед тим, як прибирати."
                    ),
                }
            )
        )
        return 1
    # Вимога чистого дерева була наслідком редагування НА МІСЦІ: аварія лишала мутацію
    # невідрізненною від чужої правки. З копією ця передумова зникла, і тримати
    # заборону далі означало б боронити те, чого вже немає, ціною працездатності.
    # Для `--in-place` вона лишається чинною дослівно.
    if args.in_place and not args.allow_dirty and not source_tree_is_clean():
        print(
            json.dumps(
                {
                    "status": "REFUSED",
                    "reason": (
                        "apps/api/src or scripts has uncommitted changes; this probe edits "
                        "files in place and a crash would leave them indistinguishable "
                        "from your own work. Commit or stash, or pass --allow-dirty."
                    ),
                }
            )
        )
        return 1

    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(f"pid={os.getpid()}\n", encoding="utf-8")

    # SIGTERM не підіймає винятку, тож `finally` його не бачить — саме так 31.08.2026
    # `timeout` лишив мутацію в дереві. Обробник переводить сигнал у виняток, і
    # відновлення відбувається тим самим шляхом, що й при помилці.
    def _terminate(signum: int, _frame: object) -> None:
        raise KeyboardInterrupt(f"signal {signum}")

    for received in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(received, _terminate)

    sandbox: str | None = None
    workspace = DEFAULT_WORKSPACE
    try:
        if not args.in_place:
            sandbox = tempfile.mkdtemp(prefix="korpus-mutation-probe-")
            workspace = Path(sandbox) / "tree"
            shutil.copytree(
                ROOT,
                workspace,
                symlinks=True,
                ignore=shutil.ignore_patterns(
                    ".git",
                    "var",
                    "reports",
                    "node_modules",
                    "__pycache__",
                    ".venv",
                    ".pytest_cache",
                    ".mypy_cache",
                    "dist",
                ),
            )
            # venv не копіюємо — він важкий і не змінюється; посилання на оригінал.
            (workspace / "apps/api/.venv").symlink_to(ROOT / "apps/api/.venv")
        return probe(args, workspace)
    finally:
        LOCK.unlink(missing_ok=True)
        if sandbox is not None:
            shutil.rmtree(sandbox, ignore_errors=True)


@dataclass(frozen=True)
class ProbePlan:
    modules: int
    available: int
    sampled: int
    seed: int
    baseline: SuiteExecution | None


def _measure(
    sample: list[Seeded], baseline: SuiteExecution, context: tuple[Path, float]
) -> list[dict[str, object]]:
    workspace, timeout = context
    results: list[dict[str, object]] = []
    for index, mutant in enumerate(sample, start=1):
        original = apply(mutant, workspace)
        mutant_digest = hashlib.sha256((workspace / mutant.module).read_bytes()).hexdigest()
        try:
            execution = suite_kills(timeout, workspace)
        finally:
            (workspace / mutant.module).write_text(original, encoding="utf-8")
        status, reason = mutation_outcome(baseline, execution)
        results.append(
            {
                "module": mutant.module,
                "line": mutant.line,
                "kind": mutant.kind,
                "mutation": f"{mutant.old.strip()} -> {mutant.new.strip()}",
                "killed": status == "KILLED",
                "source_sha256": hashlib.sha256(original.encode("utf-8")).hexdigest(),
                "mutant_sha256": mutant_digest,
                "status": status,
                "reason": reason,
                "seconds": round(execution.seconds, 3),
                "execution": execution.receipt(),
            }
        )
        print(f"[{index}/{len(sample)}] {status} {mutant.module}:{mutant.line}", flush=True)
    return results


def _measurement_status(plan: ProbePlan, results: list[dict[str, object]]) -> str:
    if not plan.sampled:
        return "NOT_MEASURED"
    if plan.baseline is None or plan.baseline.status != "PASSED":
        return "BASELINE_FAILED"
    if len(results) != plan.sampled or any(
        row["status"] not in {"KILLED", "SURVIVED"} for row in results
    ):
        return "INCONCLUSIVE"
    return "COMPLETE"


def _publish(args: argparse.Namespace, plan: ProbePlan, results: list[dict[str, object]]) -> int:
    killed = sum(row["status"] == "KILLED" for row in results)
    survivors = [row for row in results if row["status"] == "SURVIVED"]
    incomplete = [row for row in results if row["status"] not in {"KILLED", "SURVIVED"}]
    status = _measurement_status(plan, results)
    measured = status == "COMPLETE"
    interval = wilson_interval(killed, plan.sampled) if measured else None
    report = {
        "schema": "korpus.uncatalogued-mutation-probe.v2",
        "status": status,
        "modules_uncatalogued": plan.modules,
        "mutations_available": plan.available,
        "sampled": plan.sampled,
        "executed": len(results),
        "seed": plan.seed,
        "unexecuted": plan.sampled - len(results),
        "killed": killed,
        "survived": len(survivors),
        "inconclusive": len(incomplete),
        "baseline": plan.baseline.receipt() if plan.baseline is not None else None,
        "kill_rate": round(killed / plan.sampled, 4) if measured else None,
        "kill_rate_interval_95": [round(v, 4) for v in interval] if interval else None,
        "survivors": survivors,
        "inconclusive_results": incomplete,
        "results": results,
        "interpretation": (
            "A sampled measurement outside the curated catalogue, not a release gate. "
            "Only a test failure after a passing unmodified baseline is KILLED. "
            "Timeouts, pytest errors, skipped-away or missing tests are INCONCLUSIVE. "
            "No rate or interval is reported for an incomplete sample; its denominator "
            "is never reduced to hide unmeasured outcomes. Survivors require examination "
            "for equivalence and do not alone establish a product defect."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                k: v
                for k, v in report.items()
                if k not in {"results", "survivors", "inconclusive_results"}
            },
            indent=2,
        )
    )
    return 0 if measured else 2


def probe(args: argparse.Namespace, workspace: Path) -> int:
    modules = uncatalogued_modules(args.paths)
    population = [mutant for module in modules for mutant in seed_module(module, workspace)]
    sample = random.Random(args.seed).sample(population, min(max(args.sample, 0), len(population)))
    baseline = suite_kills(args.timeout, workspace) if sample else None
    plan = ProbePlan(len(modules), len(population), len(sample), args.seed, baseline)
    results = (
        _measure(sample, baseline, (workspace, args.timeout))
        if baseline and baseline.status == "PASSED"
        else []
    )
    return _publish(args, plan, results)


if __name__ == "__main__":
    sys.exit(main())
