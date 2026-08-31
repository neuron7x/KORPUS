#!/usr/bin/env python3
"""Чи те саме питання в іншій формі слова читається системою як те саме питання.

Відмова — теж твердження. Медик, який не отримав відповіді про пневмоторакс, робить
висновок про КОРПУС, а не про своє формулювання, і корпус його не спростує.

Виміряно 31.08.2026 просто в індексі: «турнікет» → 0 збігів, «турнікет*» → 3;
«поранен» → 0, «поранен*» → 260; «джавелін» → 0, «javelin» → 99; «хаймарс» → 0,
«himars» → 62. Тобто пошук точний по токену: будь-яка інша форма слова або інша
абетка — інше питання.

**Згода рахується окремо для відповідей і окремо для утримань, і це не педантизм.**
Система, що мовчить на обидва боки пари, дає ідеальну «згоду» — і це рівно те, що
ратчет на одній осі не відрізняє від справжньої стабільності. Тому звіт несе три
числа, і ратчет тримає їх разом.

Коди виходу: 0 — виміряно · 2 — вимір не відбувся (транспортна відмова не є нулем).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals/datasets/paraphrase_stability.jsonl"
META = ROOT / "evals/datasets/paraphrase_stability.meta.json"
ANSWERED = "answered"


def ask(base: str, question: str, token: str, timeout: float) -> dict[str, Any] | None:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{base.rstrip('/')}/v1/answers",
        data=json.dumps({"text": question}).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload: dict[str, Any] = json.load(response)
            return payload
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None


def summarize(observations: list[dict[str, Any]]) -> dict[str, Any]:
    """Три числа, бо одне з них завжди можна отримати мовчанням."""
    judged = [row for row in observations if row["a"] is not None and row["b"] is not None]
    both_answered = [row for row in judged if row["a"] == ANSWERED and row["b"] == ANSWERED]
    both_withheld = [row for row in judged if row["a"] != ANSWERED and row["b"] != ANSWERED]
    disagreed = [row for row in judged if (row["a"] == ANSWERED) != (row["b"] == ANSWERED)]
    return {
        "judged": len(judged),
        "agreed_answered": len(both_answered),
        "agreed_withheld": len(both_withheld),
        "disagreed": len(disagreed),
        # None, не 0.0: частка над нулем пар — відсутність виміру.
        "agreement_rate": None if not judged else (len(judged) - len(disagreed)) / len(judged),
        "answered_agreement_share": None if not judged else len(both_answered) / len(judged),
        "disagreements": [row["id"] for row in disagreed],
    }


def evaluate(rows: list[dict[str, Any]], base: str, token: str, timeout: float) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    unreachable: list[str] = []
    for row in rows:
        first, second = ask(base, row["a"], token, timeout), ask(base, row["b"], token, timeout)
        if first is None or second is None:
            unreachable.append(row["id"])
        observations.append(
            {
                "id": row["id"],
                "stratum": row["stratum"],
                "a": None if first is None else first.get("status"),
                "b": None if second is None else second.get("status"),
            }
        )
    strata = sorted({str(row["stratum"]) for row in rows})
    body = DATASET.read_text(encoding="utf-8")
    return {
        "schema": "korpus.paraphrase-stability.v1",
        "ran_at": datetime.now(UTC).isoformat(),
        "base": base,
        "set_digest": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "status": "UNKNOWN" if unreachable else "MEASURED",
        "unreachable": unreachable,
        "overall": summarize(observations),
        "by_stratum": {
            name: summarize([row for row in observations if str(row["stratum"]) == name])
            for name in strata
        },
        "cannot_judge": json.loads(META.read_text(encoding="utf-8"))["cannot_judge"],
    }


def selftest() -> int:
    """Оракул і саботажник на самому вимірювачі.

    Без них «згода 1.0» від системи, що мовчить завжди, читалась би як стабільність.
    """
    oracle: list[dict[str, Any]] = [{"id": "o", "stratum": "s", "a": "answered", "b": "answered"}]
    silent = [
        {"id": "s", "stratum": "s", "a": "insufficient_evidence", "b": "insufficient_evidence"}
    ]
    flipped: list[dict[str, Any]] = [
        {"id": "f", "stratum": "s", "a": "answered", "b": "insufficient_evidence"}
    ]
    blind: list[dict[str, Any]] = [{"id": "b", "stratum": "s", "a": None, "b": None}]
    cases: list[tuple[str, list[dict[str, Any]], float | None, float | None, int]] = [
        ("оракул: обидва відповіли", oracle, 1.0, 1.0, 0),
        ("мовчун: обидва утримались — згода є, відповідей нема", silent, 1.0, 0.0, 0),
        ("саботажник: вирок перевернувся", flipped, 0.0, 0.0, 1),
        ("сліпий: транспорт не дійшов", blind, None, None, 0),
    ]
    failures: list[str] = []
    for name, rows, rate, answered_share, disagreed in cases:
        got = summarize(rows)
        if got["agreement_rate"] != rate or got["answered_agreement_share"] != answered_share:
            failures.append(f"{name}: {got['agreement_rate']}/{got['answered_agreement_share']}")
        elif got["disagreed"] != disagreed:
            failures.append(f"{name}: розбіжностей {got['disagreed']}")
    print(json.dumps({"selftest": len(cases), "failed": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8081/api")
    parser.add_argument("--token", default="")
    parser.add_argument("--out", type=Path, default=ROOT / "var/paraphrase-eval.json")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line]
    report = evaluate(rows, args.base, args.token, args.timeout)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "MEASURED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
