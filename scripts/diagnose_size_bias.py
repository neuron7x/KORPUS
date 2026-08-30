#!/usr/bin/env python3
"""Ask whether retrieval prefers large documents over relevant ones.

Six of the reference set's failures cite a document several times larger than the one
holding the sentence asked about, and the largest is a hundred times larger. That is an
observation about failures only, and on its own it proves nothing: if passing cases cite
documents just as large, size is not the discriminator and the ratio is an artefact of
looking only where the system was wrong.

So the comparison is run on every retrieval case, passing and failing, and the null it
tests is the honest one — that the size of the cited document is the same in both groups.

The mechanism this is looking for is not a scoring bug in the usual sense. Scoring picks
the best span; a manual with a thousand spans gets a thousand draws at containing a
coincidental co-occurrence of the query's common words, while a thirty-two span analytic
paper gets thirty-two. The corpus median is eight spans and its largest document has
fifteen hundred, so the draws are not close to equal.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DECLARATION = {"given_name": "Еталон", "family_name": "Тестенко", "specialty": "перевірка"}


def _sizes(database: Path) -> dict[str, int]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        return {
            str(version): int(count)
            for version, count in connection.execute(
                "SELECT v.id, count(*) FROM evidence_spans s"
                " JOIN document_versions v ON v.id = s.version_id"
                " WHERE v.review_state = 'approved' GROUP BY v.id"
            )
        }
    finally:
        connection.close()


def _ask(base: str, text: str, token: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base}/v1/answers",
        data=json.dumps({"text": text, "declaration": DECLARATION}).encode("utf-8"),
        headers={"content-type": "application/json", "Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return dict(json.loads(response.read()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default="")
    parser.add_argument("--set", type=Path, default=ROOT / "evals/datasets/reference.jsonl")
    parser.add_argument(
        "--database", type=Path, default=ROOT / "var/runtime/corpus-v6-20260807/korpus.db"
    )
    parser.add_argument("--out", type=Path, default=ROOT / "var/size-bias.json")
    parser.add_argument("--timeout", type=float, default=60.0)
    arguments = parser.parse_args()

    size = _sizes(arguments.database)
    corpus_median = statistics.median(size.values())
    cases = [
        json.loads(line)
        for line in arguments.set.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    retrieval = [case for case in cases if case["kind"] == "retrieval"]

    passed: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for case in retrieval:
        answer = _ask(arguments.base, case["query"], arguments.token, arguments.timeout)
        if str(answer.get("status")) != "answered":
            continue
        cited = {str(c.get("version_id")) for c in (answer.get("citations") or [])}
        holders = set(case["must_cite_one_of_if_answered"])
        record = {
            "id": case["id"],
            "cited_size": max((size.get(v, 0) for v in cited), default=0),
            "expected_size": max((size.get(v, 0) for v in holders), default=0),
        }
        (passed if cited & holders else failed).append(record)

    def summarise(group: list[dict[str, Any]]) -> dict[str, Any]:
        cited = [item["cited_size"] for item in group]
        expected = [item["expected_size"] for item in group]
        ratios = [
            item["cited_size"] / item["expected_size"]
            for item in group
            if item["expected_size"] > 0
        ]
        return {
            "cases": len(group),
            "cited_size_median": statistics.median(cited) if cited else 0,
            "expected_size_median": statistics.median(expected) if expected else 0,
            "cited_over_expected_median": statistics.median(ratios) if ratios else 0,
            "cited_bigger_than_expected": sum(1 for value in ratios if value > 1),
        }

    report = {
        "base": arguments.base,
        "corpus_documents": len(size),
        "corpus_span_median": corpus_median,
        "corpus_span_max": max(size.values()),
        # The comparison the finding stands or falls on. If these two lines look alike,
        # size is not what separates a right answer from a wrong one here.
        "passed": summarise(passed),
        "failed": summarise(failed),
        "detail_failed": failed,
    }
    arguments.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(
        json.dumps(
            {k: v for k, v in report.items() if k != "detail_failed"}, ensure_ascii=False, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
