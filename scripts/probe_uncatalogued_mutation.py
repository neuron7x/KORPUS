#!/usr/bin/env python3
"""Measure the half of the tree the curated mutation catalogue does not reach.

`run_mutation_tests.py` carries 349 hand-written mutants over 126 modules, and reports
`mutation_score_over_catalogue: 1.0`. That number is true and it is about the catalogue.
Measured 2026-08-29, 162 modules and 15 853 lines — 42% of the source — carry no mutant
at all, so the score says nothing about them. A curated catalogue is the stronger
instrument where it reaches; the question this answers is what the suite is worth where
it does not.

The probe is deliberately not a gate and deliberately not curated. It seeds ordinary
operator mutations by AST — a comparison flipped, a boolean operator swapped, a guard
short-circuited — samples them with a fixed seed, and runs the suite against each one.
A mutant the suite kills is evidence for the tests over that line; a survivor is a line
whose behaviour no test distinguishes, which is a candidate for the curated catalogue
rather than a defect on its own.

Sampling is what makes it affordable: the full suite is three minutes, so an exhaustive
seed over 15 853 lines is not a thing anyone runs. `-x` stops at the first failure, which
makes a killed mutant cheap and leaves the cost with survivors — the outcome worth paying
for.

It edits files in place and restores them, so nothing else may read the tree while it
runs. That is not a theoretical hazard: a `make validate` started alongside the first run
of this probe read a mutated module and reported two model-checker failures that did not
reproduce in twelve subsequent runs. A lock file makes the overlap impossible instead of
unlikely, and a dirty tree is refused because a crash mid-run would otherwise be
indistinguishable from uncommitted work.
"""

from __future__ import annotations

import argparse
import ast
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
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "apps/api/src/korpus"
CATALOGUE = ROOT / "scripts/run_mutation_tests.py"
LOCK = ROOT / "var/mutation-probe.lock"

#: Типове дерево. Робоче передається ПАРАМЕТРОМ: глобал тут був би прихованим
#: передаванням стану, а стан цієї програми — саме те, що вона лишає в дереві.
#:
#: Дерево, яке проба РЕДАГУЄ. За замовчуванням — окрема копія, і це не обережність,
#: а виправлення класу дефекту.
#:
#: 31.08.2026 прогін було вбито `timeout` (SIGTERM). Обробника сигналу не було, тож
#: `finally` не виконався, і мутація лишилась у дереві:
#: `adaptive_contracts.py:92` стояв із `or` замість `and` — ослаблений валідатор, що
#: приймає нецілі значення, бо `x >= 0` істинне для float. Це те саме дерево, з якого
#: імпортує ЖИВИЙ API: перезапуск сервера у тому вікні підняв би ослаблену перевірку.
#: Знайдено випадково, суцільним `ruff format`, а не перевіркою.
#:
#: Копія прибирає клас цілком: що б не сталося з процесом, редагується не те дерево,
#: яке обслуговує читача. `--in-place` лишається для налагодження й попереджає про себе.
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
    """Некаталогізовані модулі; `only` звужує предмет до названих шляхів.

    Звуження потрібне гейту дельти: без нього проба або міряє все дерево (162
    модулі, години), або не міряє нічого. Названий предмет — умова того, щоб
    вимір був дешевим і при цьому лишався виміром, а не вибіркою навмання.
    Шлях, якого немає серед некаталогізованих, НЕ мовчить: він або каталогізований
    (і тоді його міряє курована кампанія), або не існує — і це різні стани.
    """
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
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    lines[mutant.line - 1] = lines[mutant.line - 1].replace(mutant.old, mutant.new, 1)
    path.write_text("".join(lines), encoding="utf-8")
    return original


def suite_kills(timeout_seconds: float, workspace: Path) -> tuple[bool, float]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "apps/api/tests",
                "-x",
                "-q",
                "--no-cov",
                "-p",
                "no:cacheprovider",
            ],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(workspace / "apps/api/src")},
            check=False,
        )
    except subprocess.TimeoutExpired:
        # A mutant that makes the suite hang is killed by the timeout: the behaviour
        # changed observably. Recorded separately so the count is never mistaken for a
        # test asserting something.
        return True, time.monotonic() - started
    return completed.returncode != 0, time.monotonic() - started


def _lock_pid() -> int | None:
    try:
        text = LOCK.read_text(encoding="utf-8")
    except OSError:
        return None
    found = re.search(r"pid=(\d+)", text)
    return int(found.group(1)) if found else None


def _lock_holder_alive() -> bool:
    """Чи справді хтось тримає замок.

    Замок без цієї перевірки блокує НАЗАВЖДИ після будь-якого аварійного виходу, і
    саме так виглядав стан 31.08.2026: власник мертвий, замок на місці, наступний
    прогін відмовляється стартувати без пояснення причини.
    """
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


def probe(args: argparse.Namespace, workspace: Path) -> int:
    modules = uncatalogued_modules(args.paths)
    population: list[Seeded] = []
    for module in modules:
        population.extend(seed_module(module, workspace))

    rng = random.Random(args.seed)
    sample = rng.sample(population, min(args.sample, len(population)))

    results: list[dict[str, object]] = []
    for index, mutant in enumerate(sample, start=1):
        original = apply(mutant, workspace)
        try:
            killed, elapsed = suite_kills(args.timeout, workspace)
        finally:
            (workspace / mutant.module).write_text(original, encoding="utf-8")
        results.append(
            {
                "module": mutant.module,
                "line": mutant.line,
                "kind": mutant.kind,
                "mutation": f"{mutant.old.strip()} -> {mutant.new.strip()}",
                "killed": killed,
                "seconds": round(elapsed, 1),
            }
        )
        print(
            f"[{index}/{len(sample)}] {'KILLED ' if killed else 'SURVIVED'} "
            f"{mutant.module}:{mutant.line} {mutant.old.strip()} -> {mutant.new.strip()}",
            flush=True,
        )

    killed_total = sum(1 for row in results if row["killed"])
    # A sampled rate without its interval invites reading 60/60 as "the suite kills
    # everything". It does not: it means the rate is not below the lower bound, and with
    # sixty draws that bound is 0.94, not 1.0.
    lower, upper = wilson_interval(killed_total, len(sample)) if sample else (0.0, 1.0)
    report = {
        "schema": "korpus.uncatalogued-mutation-probe.v1",
        "modules_uncatalogued": len(modules),
        "mutations_available": len(population),
        "sampled": len(sample),
        "seed": args.seed,
        "killed": killed_total,
        "survived": len(sample) - killed_total,
        "kill_rate": round(killed_total / len(sample), 4) if sample else None,
        "kill_rate_interval_95": [round(lower, 4), round(upper, 4)],
        "survivors": [row for row in results if not row["killed"]],
        "results": results,
        "interpretation": (
            "A measurement of the suite outside the curated catalogue, not a gate. "
            "The rate is sampled, so the interval is the claim and the point estimate is "
            "not: 60 of 60 killed bounds the true rate at 0.94 or better, never at 1.0. "
            "Survivors are lines whose behaviour no test distinguishes; each is a "
            "candidate for the curated catalogue, and an equivalent mutation is a "
            "possible explanation that has to be checked one by one."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {k: v for k, v in report.items() if k not in {"results", "survivors"}},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
