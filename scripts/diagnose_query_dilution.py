#!/usr/bin/env python3
"""Does adding words to a question make retrieval worse?

Two reference failures looked decisive. "cwix24" is a token this library holds in exactly
one document, and asked alone it returns that document and the very sentence the case was
built from. Asked as "cwix24 praise impressed professionalism amid representatives" — the
same token plus five ordinary English words — it returns FM 3-09, a manual eleven hundred
spans long that happens to contain one sentence about people being impressed by someone's
professionalism. The reading suggested itself immediately: the rare term is diluted, a
large document wins on coincidental co-occurrence, and therefore the more a soldier types
the worse the answer gets.

That last clause is the part worth testing, because it is the part that would change the
product. This runs both forms of every retrieval question in the frozen set — the whole
query, and its rarest term alone, which `_distinctive` puts first — and counts which finds
a version holding the sentence.

Measured 2026-08-30 against the deployed corpus: the whole question wins, 69 of 79 against
59 of 79. Dilution is real and it is rare — three cases in seventy-nine — and the general
claim it seemed to support is false in the opposite direction. Extra context helps. Keep
this script rather than the conclusion: the conclusion is a number about one corpus on one
day, and the corpus grows.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DECLARATION = {"given_name": "Еталон", "family_name": "Тестенко", "specialty": "перевірка"}


def _ask(base: str, text: str, token: str, timeout: float) -> tuple[str, set[str]]:
    request = urllib.request.Request(
        f"{base}/v1/answers",
        data=json.dumps({"text": text, "declaration": DECLARATION}).encode("utf-8"),
        headers={"content-type": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            answer = dict(json.loads(response.read()))
    except (OSError, urllib.error.URLError, TimeoutError) as error:
        # An unreachable server is not a retrieval miss, and counting it as one would put
        # the network into the measurement. It is named and excluded.
        return f"unreachable:{type(error).__name__}", set()
    citations = answer.get("citations") or []
    return str(answer.get("status", "")), {
        str(citation.get("version_id")) for citation in citations if citation.get("version_id")
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default="")
    parser.add_argument("--set", type=Path, default=ROOT / "evals/datasets/reference.jsonl")
    parser.add_argument("--out", type=Path, default=ROOT / "var/query-dilution.json")
    parser.add_argument("--timeout", type=float, default=60.0)
    arguments = parser.parse_args()

    cases = [
        json.loads(line)
        for line in arguments.set.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    retrieval = [case for case in cases if case["kind"] == "retrieval"]

    rows: list[dict[str, Any]] = []
    unreachable = 0
    for case in retrieval:
        holders = set(case["must_cite_one_of_if_answered"])
        rarest = case["query"].split()[0]
        full_status, full_cited = _ask(
            arguments.base, case["query"], arguments.token, arguments.timeout
        )
        rare_status, rare_cited = _ask(arguments.base, rarest, arguments.token, arguments.timeout)
        if full_status.startswith("unreachable") or rare_status.startswith("unreachable"):
            unreachable += 1
            continue
        rows.append(
            {
                "id": case["id"],
                "stratum": case["stratum"],
                "query": case["query"],
                "rarest_term": rarest,
                "full_hits": bool(full_cited & holders),
                "rarest_hits": bool(rare_cited & holders),
                "full_status": full_status,
            }
        )

    diluted = [row for row in rows if row["rarest_hits"] and not row["full_hits"]]
    report = {
        "base": arguments.base,
        "cases": len(rows),
        "unreachable": unreachable,
        "full_query_hits": sum(1 for row in rows if row["full_hits"]),
        "rarest_term_hits": sum(1 for row in rows if row["rarest_hits"]),
        "both": sum(1 for row in rows if row["full_hits"] and row["rarest_hits"]),
        "only_full": sum(1 for row in rows if row["full_hits"] and not row["rarest_hits"]),
        "only_rarest": len(diluted),
        "neither": sum(1 for row in rows if not row["full_hits"] and not row["rarest_hits"]),
        "diluted": diluted,
        "verdict": (
            "Dilution is present only where only_rarest is greater than only_full. The "
            "count that matters is the difference, not the existence of examples: two "
            "vivid cases were found before this was run, and the sweep showed the whole "
            "question wins overall."
        ),
    }
    arguments.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(
        json.dumps(
            {k: v for k, v in report.items() if k != "diluted"}, ensure_ascii=False, indent=2
        )
    )
    for row in diluted:
        print(f"  розчинення: {row['id']:<34} '{row['rarest_term']}'  ←  '{row['query']}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
