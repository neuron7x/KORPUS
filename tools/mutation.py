#!/usr/bin/env python3
"""Mutation gate.

Coverage says a line ran. This says the suite notices when the line is wrong.

Each mutant is one textual substitution that changes behaviour in a way a competent
reviewer would call a defect. A mutant that survives is a hole in the suite, named
and located. The catalogue lives in `tools/mutants.json`; the floor lives in
`tools/mutation_baseline.json`.

Three ways this exits non-zero, all deliberate:
  * kill rate below the ratchet floor;
  * a catalogue entry whose pattern no longer exists in the source (a silently
    shrinking gate is worse than a red one);
  * a baseline that no longer matches the catalogue size.

Usage:
  python3 tools/mutation.py                 # gate: run every mutant, enforce the floor
  python3 tools/mutation.py --only access   # subset by file or mutant id
  python3 tools/mutation.py --update-baseline
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "tools/mutants.json"
BASELINE = ROOT / "tools/mutation_baseline.json"
_VENV_PYTHON = ROOT / "apps/api/.venv/bin/python"
# Local runs use the project venv; CI has the package installed into the image python.
INTERPRETER = str(_VENV_PYTHON) if _VENV_PYTHON.exists() else sys.executable
# One mutant must not outlive the run. A defect that makes the suite hang would
# otherwise consume the whole CI budget and be reported as nothing at all.
SUITE_TIMEOUT_SECONDS = 300
IGNORED = shutil.ignore_patterns(
    ".git", ".venv", "node_modules", ".next", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".pnpm-store", "htmlcov",
)


@dataclass
class Mutant:
    id: str
    file: str
    description: str
    old: str
    new: str
    equivalent: bool = False
    """Marked equivalent only with a proof written into the description.

    An equivalent mutant is excluded from the kill rate — counting it would let the
    denominator hide behind unkillable entries — but it is still executed, because a
    mutant that suddenly becomes killable means the code moved under it.
    """

    def path_in(self, tree: Path) -> Path:
        return tree / self.file


def load_mutants() -> list[Mutant]:
    raw = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    return [
        Mutant(**{k: v for k, v in entry.items() if not k.startswith("$")})
        for entry in raw["mutants"]
    ]


def run_suite(tree: Path) -> int:
    """Run the suite inside `tree`. Timeout counts as detection, not as survival."""
    command = [
        INTERPRETER, "-m", "pytest", str(tree / "apps/api/tests"),
        "-x", "-q", "--no-header", "-p", "no:cacheprovider",
    ]
    try:
        return subprocess.run(
            command, cwd=tree, capture_output=True, text=True,
            timeout=SUITE_TIMEOUT_SECONDS, check=False,
        ).returncode
    except subprocess.TimeoutExpired:
        return 124


def apply_and_run(mutant: Mutant, tree: Path) -> tuple[str, int | None]:
    """Mutate a scratch copy of the repository, never the working tree.

    Editing the real files in place means a SIGTERM — which is exactly what a CI job
    timeout sends — leaves the defect written to disk and the run reports nothing.
    """
    target = mutant.path_in(tree)
    original = target.read_text(encoding="utf-8")
    occurrences = original.count(mutant.old)
    if occurrences == 0:
        return "stale", None
    if occurrences > 1:
        return "ambiguous", None
    try:
        target.write_text(original.replace(mutant.old, mutant.new, 1), encoding="utf-8")
        code = run_suite(tree)
    finally:
        target.write_text(original, encoding="utf-8")
    if code == 124:
        return "timeout", code
    return ("killed" if code != 0 else "survived"), code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--only",
        dest="subset",
        default=None,
        help="substring filter on id or file; a subset run never enforces the floor",
    )
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    mutants = load_mutants()
    if args.subset:
        mutants = [m for m in mutants if args.subset in m.id or args.subset in m.file]
    if not mutants:
        print("FAIL: no mutants selected")
        return 2

    scratch = Path(tempfile.mkdtemp(prefix="korpus-mutation-"))
    tree = scratch / "repo"
    shutil.copytree(ROOT, tree, ignore=IGNORED, symlinks=True)

    baseline_code = run_suite(tree)
    if baseline_code != 0:
        shutil.rmtree(scratch, ignore_errors=True)
        print(f"FAIL: the suite is red before mutation (exit {baseline_code})")
        return 2

    killed: list[str] = []
    survived: list[Mutant] = []
    stale: list[str] = []
    ambiguous: list[str] = []
    timeouts: list[str] = []
    broken_equivalence: list[str] = []

    for mutant in mutants:
        outcome, _ = apply_and_run(mutant, tree)
        if outcome == "timeout":
            timeouts.append(mutant.id)
            killed.append(mutant.id)
            marker = "timeout"
        elif outcome == "stale":
            stale.append(mutant.id)
            marker = "STALE"
        elif outcome == "ambiguous":
            ambiguous.append(mutant.id)
            marker = "AMBIGUOUS"
        elif mutant.equivalent:
            marker = "equivalent"
            if outcome == "killed":
                broken_equivalence.append(mutant.id)
                marker = "NOT-EQUIV"
        elif outcome == "killed":
            killed.append(mutant.id)
            marker = "killed"
        else:
            survived.append(mutant)
            marker = "SURVIVED"
        if not args.json:
            print(f"  {marker:>10}  {mutant.id}  {mutant.description}")

    scored = len(killed) + len(survived)
    rate = len(killed) / scored if scored else 0.0

    baseline = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    floor = float(baseline.get("minimum_kill_rate", 0.0))

    if args.update_baseline:
        BASELINE.write_text(
            json.dumps(
                {
                    "minimum_kill_rate": round(rate, 4),
                    "catalogue_size": len(load_mutants()),
                    "note": (
                        "Ratchet floor. Raise it when the suite improves; "
                        "never lower it quietly."
                    ),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"baseline updated to {rate:.4f} over {len(load_mutants())} mutants")
        shutil.rmtree(scratch, ignore_errors=True)
        return 0

    # Failure reasons are collected before printing, so the JSON report is valid JSON
    # in every outcome — a report that turns into prose on failure is unparseable by
    # the one consumer that matters, the pipeline reading it.
    failures: list[str] = []
    if stale or ambiguous:
        failures.append(f"catalogue out of date — stale={stale} ambiguous={ambiguous}")
    if broken_equivalence:
        failures.append(
            "mutants marked equivalent were killed, the proof no longer holds: "
            f"{broken_equivalence}"
        )
    expected_size = int(baseline.get("catalogue_size", len(mutants)))
    if not args.subset and len(mutants) < expected_size:
        failures.append(f"catalogue shrank from {expected_size} to {len(mutants)} mutants")
    if not args.subset and rate + 1e-9 < floor:
        failures.append(f"kill rate {rate:.4f} below floor {floor:.4f}")

    summary = {
        "scored": scored,
        "killed": len(killed),
        "survived": len(survived),
        "kill_rate": round(rate, 4),
        "floor": floor,
        "subset": bool(args.subset),
        "stale": stale,
        "ambiguous": ambiguous,
        "timeouts": timeouts,
        "survivors": [{"id": m.id, "file": m.file, "description": m.description} for m in survived],
        "failures": failures,
        "verdict": "fail" if failures else "pass",
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        scope = " [SUBSET — floor not enforced]" if args.subset else ""
        print(f"\nkilled {len(killed)}/{scored} = {rate:.4f} (floor {floor:.4f}){scope}")
        for mutant in survived:
            print(f"  survivor: {mutant.id} — {mutant.description} [{mutant.file}]")
        for reason in failures:
            print(f"FAIL: {reason}")

    shutil.rmtree(scratch, ignore_errors=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
