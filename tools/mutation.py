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
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "tools/mutants.json"
BASELINE = ROOT / "tools/mutation_baseline.json"
_VENV_PYTHON = ROOT / "apps/api/.venv/bin/python"
# Local runs use the project venv; CI has the package installed into the image python.
INTERPRETER = str(_VENV_PYTHON) if _VENV_PYTHON.exists() else sys.executable
PYTEST = [
    INTERPRETER,
    "-m",
    "pytest",
    str(ROOT / "apps/api/tests"),
    "-x",
    "-q",
    "--no-header",
    "-p",
    "no:cacheprovider",
]


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

    @property
    def path(self) -> Path:
        return ROOT / self.file


def load_mutants() -> list[Mutant]:
    raw = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    return [Mutant(**entry) for entry in raw["mutants"]]


def run_suite() -> int:
    return subprocess.run(PYTEST, cwd=ROOT, capture_output=True, text=True).returncode


def apply_and_run(mutant: Mutant) -> tuple[str, int | None]:
    """Returns (outcome, exit_code). The original file is always restored."""
    original = mutant.path.read_text(encoding="utf-8")
    occurrences = original.count(mutant.old)
    if occurrences == 0:
        return "stale", None
    if occurrences > 1:
        return "ambiguous", None
    try:
        mutant.path.write_text(original.replace(mutant.old, mutant.new, 1), encoding="utf-8")
        code = run_suite()
    finally:
        mutant.path.write_text(original, encoding="utf-8")
        assert mutant.path.read_text(encoding="utf-8") == original
    return ("killed" if code != 0 else "survived"), code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default=None, help="substring filter on id or file")
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    mutants = load_mutants()
    if args.only:
        mutants = [m for m in mutants if args.only in m.id or args.only in m.file]
    if not mutants:
        print("FAIL: no mutants selected")
        return 2

    baseline_code = run_suite()
    if baseline_code != 0:
        print(f"FAIL: the suite is red before mutation (exit {baseline_code})")
        return 2

    killed: list[str] = []
    survived: list[Mutant] = []
    stale: list[str] = []
    ambiguous: list[str] = []
    broken_equivalence: list[str] = []

    for mutant in mutants:
        outcome, _ = apply_and_run(mutant)
        if outcome == "stale":
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
                    "note": "Ratchet floor. Raise it when the suite improves; never lower it silently.",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"baseline updated to {rate:.4f} over {len(load_mutants())} mutants")
        return 0

    summary = {
        "scored": scored,
        "killed": len(killed),
        "survived": len(survived),
        "kill_rate": round(rate, 4),
        "floor": floor,
        "stale": stale,
        "ambiguous": ambiguous,
        "survivors": [{"id": m.id, "file": m.file, "description": m.description} for m in survived],
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"\nkilled {len(killed)}/{scored} = {rate:.4f} (floor {floor:.4f})")
        for mutant in survived:
            print(f"  survivor: {mutant.id} — {mutant.description} [{mutant.file}]")

    if stale or ambiguous:
        print(f"FAIL: catalogue out of date — stale={stale} ambiguous={ambiguous}")
        return 3
    if broken_equivalence:
        print(
            "FAIL: mutants marked equivalent were killed — the proof no longer holds: "
            f"{broken_equivalence}"
        )
        return 3
    expected_size = int(baseline.get("catalogue_size", len(mutants)))
    if not args.only and len(mutants) < expected_size:
        print(f"FAIL: catalogue shrank from {expected_size} to {len(mutants)} mutants")
        return 3
    if rate + 1e-9 < floor:
        print(f"FAIL: kill rate {rate:.4f} below floor {floor:.4f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
