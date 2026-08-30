#!/usr/bin/env python3
"""A claim about this system's own gates exists in the ledger or it does not exist.

Two sessions spent a day trading findings in chat. Every verdict in that conversation was
real work — poisons run, exit codes read — and none of it survived the conversation. A
statement that lives only in a message is not evidence anybody can check later, and the
same claim gets re-litigated by whoever reads the code next.

The rules are the ones that made the findings worth having:

  1. A verdict on a claim may not come from the actor who made it. Producer and acceptor
     being the same is the failure this whole day was about — an implementation agent
     verifying its own implementation reports what it already believed.
  2. Refuting yourself is exempt. Withdrawing a claim needs no second party, and making it
     hard would only buy silence.
  3. OPEN_FOR_REVIEW from the producer is a request, not a verdict. It stays unsigned.
     CANNOT_ADJUDICATE from a reviewer is the same shape from the other side: a statement
     that this reviewer has no measurement of their own, recorded rather than left silent.
  4. One independent REFUTED outranks any number of ACCEPTED. A defect found once is found.
  5. Append-only. A later entry supersedes an earlier one; nothing is edited or deleted,
     so being wrong earlier stays visible.

    verify_verdict_ledger.py            # human-readable
    verify_verdict_ledger.py --json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / ".verdict-ledger.jsonl"

#: A verdict that settles a claim. OPEN_FOR_REVIEW deliberately does not.
SETTLING = frozenset({"ACCEPTED", "REFUTED", "ACKNOWLEDGED"})
SELF_ALLOWED = frozenset({"REFUTED", "OPEN_FOR_REVIEW", "CANNOT_ADJUDICATE"})
#: Кожне слово, яким узагалі можна винести вирок. Невідоме слово раніше просто не
#: зараховувалось до тих, що закривають твердження, — тобто друкарська помилка в
#: `ACCEPTED` мовчки перетворювала вирок на тишу, і журнал звітував PASS. Тиша в одязі
#: вироку — це рівно те, від чого журнал існує.
#:
#: `CANNOT_ADJUDICATE` — окреме слово, а не мовчання. «Я не маю власного виміру, і
#: підписати означало б перетворити довіру на вирок» — це твердження про рецензента, і
#: воно варте запису: воно каже, ЧОМУ твердження досі не закрите, і кому його показати.
#: Той самий клас, що SCOPE_UNDECLARED у handoff-перевірці: «не можу судити» — інше
#: речення, ніж «усе гаразд», і правдиве з них лише одне.
KNOWN_VERDICTS = SETTLING | {"OPEN_FOR_REVIEW", "CANNOT_ADJUDICATE"}


def _rows() -> list[dict[str, Any]]:
    if not LEDGER.is_file():
        raise SystemExit(f"{LEDGER.name} is missing — a claim nobody recorded is not a claim")
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(LEDGER.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{LEDGER.name}:{number} is not JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise SystemExit(f"{LEDGER.name}:{number} is not an object")
        rows.append(value)
    return rows


def evaluate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    claims = {str(r["id"]): r for r in rows if r.get("kind") == "claim"}
    verdicts = [r for r in rows if r.get("kind") == "verdict"]
    problems: list[str] = []

    for verdict in verdicts:
        identifier = str(verdict.get("id", ""))
        claim = claims.get(identifier)
        if claim is None:
            problems.append(f"verdict on {identifier!r} names no claim in this ledger")
            continue
        outcome = str(verdict.get("verdict", ""))
        if outcome not in KNOWN_VERDICTS:
            problems.append(
                f"{identifier}: {outcome!r} не є вироком — слово поза словником не закриває "
                f"твердження й не відрізняється від мовчання (відомі: {sorted(KNOWN_VERDICTS)})"
            )
        if claim.get("actor") == verdict.get("actor") and outcome not in SELF_ALLOWED:
            problems.append(
                f"{identifier}: {outcome} signed by the actor who made the claim — "
                "the producer cannot be the acceptor, which is the finding this ledger exists "
                "to keep"
            )
        if not verdict.get("note") and not verdict.get("evidence"):
            problems.append(f"{identifier}: {outcome} carries neither a note nor evidence")

    settled: set[str] = set()
    refuted: set[str] = set()
    for verdict in verdicts:
        identifier = str(verdict.get("id", ""))
        outcome = str(verdict.get("verdict", ""))
        if outcome not in SETTLING:
            continue
        claim = claims.get(identifier)
        if claim is not None and claim.get("actor") != verdict.get("actor"):
            settled.add(identifier)
        if outcome == "REFUTED":
            refuted.add(identifier)

    unsigned = sorted(set(claims) - settled)
    return {
        "status": "PASS" if not problems else "FAIL",
        "claims": len(claims),
        "verdicts": len(verdicts),
        "independently_settled": len(settled),
        "unsigned": unsigned,
        "refuted": sorted(refuted),
        "problems": problems,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args()
    report = evaluate(_rows())
    if arguments.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"verdict ledger: {report['status']}")
        print(
            f"  {report['claims']} claims · {report['verdicts']} verdicts · "
            f"{report['independently_settled']} independently settled"
        )
        if report["unsigned"]:
            print(f"  awaiting an independent verdict: {', '.join(report['unsigned'])}")
        if report["refuted"]:
            print(f"  refuted: {', '.join(report['refuted'])}")
        for problem in report["problems"]:
            print(f"  x {problem}")
    # Unsigned claims are the state of the work, not a failure of the ledger.
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
