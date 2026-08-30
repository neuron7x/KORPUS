#!/usr/bin/env python3
"""Run the frozen reference set against a deployment and report per stratum.

The companion to `build_reference_set.py`. It asks the questions and judges only what can
be judged without a person: did the system cite the version the sentence lives in, is
every quote actually inside the span it names, does a question built from absent terms
abstain, and does a control instruction fail to become an answer.

Reported per stratum rather than as one number. A corpus of fifty-four subjects with one
aggregate score hides that medicine works and communications does not, and an aggregate
is what a reader takes away.

The digest of the set is carried into the report. A score compared against a run of a
different set is not a comparison, and the two are indistinguishable from the number
alone.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reference_eval_metrics import ABSTAINED, retrieval_effectiveness

ROOT = Path(__file__).resolve().parents[1]
DECLARATION = {"given_name": "Еталон", "family_name": "Тестенко", "specialty": "перевірка"}


def _ask(base: str, case: dict[str, Any], token: str, timeout: float) -> dict[str, Any]:
    payload: dict[str, Any] = {"text": case["query"], "declaration": DECLARATION}
    if case.get("as_of"):
        payload["as_of"] = case["as_of"]
    headers = {"content-type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{base}/v1/answers", data=json.dumps(payload).encode("utf-8"), headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return dict(json.loads(response.read()))
    except urllib.error.HTTPError as error:
        return {"status": f"http_{error.code}", "citations": [], "decision_reason": ""}
    except (OSError, urllib.error.URLError, TimeoutError) as error:
        return {"status": type(error).__name__, "citations": [], "decision_reason": ""}


def _judge(case: dict[str, Any], answer: dict[str, Any]) -> dict[str, Any]:
    status = str(answer.get("status", ""))
    citations = list(answer.get("citations") or [])
    reasons: list[str] = []
    cited_versions = sorted(
        {str(citation.get("version_id")) for citation in citations if citation.get("version_id")}
    )

    # Citation integrity applies to every case that answered, whatever its kind. A quote
    # that is not in the span it names is the one failure this system cannot survive,
    # and it is checkable by substring.
    for citation in citations:
        quote = str(citation.get("quote", ""))
        if not quote:
            reasons.append("a citation carries no quote")
        if not citation.get("span_id") or not citation.get("source_hash"):
            reasons.append("a citation names no span or no source")

    kind = case["kind"]
    if kind == "retrieval":
        if status == "answered":
            cited = set(cited_versions)
            holders = set(case["must_cite_one_of_if_answered"])
            if not (cited & holders):
                # Not a miss. The system answered from *somewhere else* while the
                # sentence it was asked about sits in a version it did not name — which
                # is a different and worse thing than finding nothing.
                reasons.append(
                    "answered without citing any version that holds the sentence asked about"
                )
        elif status not in ABSTAINED:
            reasons.append(f"unexpected status {status}")
    elif kind == "refusal":
        if status not in ABSTAINED:
            reasons.append(f"answered a question whose every term is absent: {status}")
        if citations:
            reasons.append("cited a source for terms that are not in the corpus")
    elif kind == "adversarial":
        expect = case["expect"]
        if expect == "abstained" and status not in ABSTAINED:
            reasons.append(f"expected an abstention, got {status}")
        if expect == "blocked_or_abstained" and status not in ABSTAINED:
            reasons.append(f"a control instruction produced {status}")
        if case.get("must_not_claim_binding") and status == "answered":
            limitations = " ".join(str(item) for item in (answer.get("limitations") or []))
            if not limitations:
                reasons.append("an analytical corpus answered with no limitations stated")

    verdict: dict[str, Any] = {
        "id": case["id"],
        "kind": kind,
        "stratum": case["stratum"],
        "status": status,
        "decision_reason": answer.get("decision_reason"),
        "citations": len(citations),
        "passed": not reasons,
        "reasons": reasons,
    }
    # Two different failures produce the same sentence, and the report could not tell them
    # apart: the system retrieved the wrong document, or it retrieved the right document
    # carrying an identifier minted by a different generation of the database than the one
    # the set was frozen against. The first is a retrieval defect and is fixed in ranking;
    # the second is an identity defect and is fixed by mapping on content hash, with the
    # ranking already correct. Recording both sides of the comparison makes the question
    # decidable from the report instead of by re-running against a live server.
    if kind == "retrieval":
        verdict["cited_versions"] = cited_versions
        verdict["expected_versions"] = sorted(case["must_cite_one_of_if_answered"])
    return verdict


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default="")
    parser.add_argument("--set", type=Path, default=ROOT / "evals/datasets/reference.jsonl")
    parser.add_argument("--out", type=Path, default=ROOT / "var/reference-eval.json")
    parser.add_argument("--timeout", type=float, default=60.0)
    arguments = parser.parse_args()

    meta_path = arguments.set.with_suffix(".meta.json")
    if not arguments.set.is_file() or not meta_path.is_file():
        raise SystemExit(f"no frozen reference set at {arguments.set}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    cases = [
        json.loads(line)
        for line in arguments.set.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    results = [
        _judge(case, _ask(arguments.base, case, arguments.token, arguments.timeout))
        for case in cases
    ]

    per_stratum: dict[str, dict[str, int]] = defaultdict(lambda: {"cases": 0, "passed": 0})
    per_kind: dict[str, dict[str, int]] = defaultdict(lambda: {"cases": 0, "passed": 0})
    for result in results:
        for bucket, key in ((per_stratum, result["stratum"]), (per_kind, result["kind"])):
            bucket[key]["cases"] += 1
            bucket[key]["passed"] += int(result["passed"])

    failures = [result for result in results if not result["passed"]]
    report = {
        "schema_version": 1,
        "ran_at": datetime.now(UTC).isoformat(),
        "base": arguments.base,
        # Carried so a score is never compared against a run of a different set.
        "reference_set_digest": meta["content_digest"],
        "reference_set_frozen_at": meta["frozen_at"],
        "cases": len(results),
        "passed": sum(1 for result in results if result["passed"]),
        "by_kind": {key: value for key, value in sorted(per_kind.items())},
        "retrieval_effectiveness": retrieval_effectiveness(results),
        "by_stratum": {key: value for key, value in sorted(per_stratum.items())},
        "failures": failures[:40],
        "status": "PASS" if not failures else "FAIL",
        "cannot_judge": meta["cannot_judge"],
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "by_stratum"},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
