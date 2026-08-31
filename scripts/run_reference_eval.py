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
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reference_eval_metrics import ABSTAINED, retrieval_effectiveness

ROOT = Path(__file__).resolve().parents[1]
DECLARATION = {"given_name": "Еталон", "family_name": "Тестенко", "specialty": "перевірка"}
#: Скільки разів перепитати, коли розгортання відповіло «зайнято». Мале число навмисно:
#: прогін, який довбить сервер, міряє чергу, а не пошук.
RETRY_ON_BUSY = 2
BUSY_BACKOFF_SECONDS = 1.5


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
    # 429 — це контроль допуску, а не вирок: розгортання тримає `max_concurrent_answers`,
    # і прогін на 95 питань його перевищує. Відповідь ІСНУЄ й дістається повторною спробою,
    # тож спершу пробуємо ще раз, і лише потім називаємо це відсутністю виміру. Виміряно
    # 31.08.2026: `adv-history-01` рахувався провалом «expected an abstention, got http_429».
    for attempt in range(RETRY_ON_BUSY + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return dict(json.loads(response.read()))
        except urllib.error.HTTPError as error:
            if error.code == 429 and attempt < RETRY_ON_BUSY:
                time.sleep(BUSY_BACKOFF_SECONDS * (attempt + 1))
                continue
            return {"status": f"http_{error.code}", "citations": [], "decision_reason": ""}
        except (OSError, urllib.error.URLError, TimeoutError) as error:
            return {"status": type(error).__name__, "citations": [], "decision_reason": ""}
    return {"status": "http_429", "citations": [], "decision_reason": ""}


#: A status the deployment never chose. `_ask` puts the transport failure in the status
#: field, so an unreachable server, a 503 from admission control and a database that went
#: away all arrive shaped exactly like a verdict — and the judge scored them as wrong
#: answers. Found 2026-08-30: a run of the hybrid configuration reported 49 of 95 with
#: refusal at 0 of 12, which read as "semantics destroyed the abstention discipline". 38
#: of those 40 failures were HTTP 503 carrying `{"reason":"database"}`. The configuration
#: had not answered a single one of them.
#:
#: These are not failures and they are not passes. They are the absence of a measurement,
#: and the report says so rather than folding them into a rate.
def _unavailable(status: str) -> bool:
    # `http_429` тут разом із 5xx і з тієї ж причини: контроль допуску відхилив за
    # навантаженням. Він 4xx, тому й не потрапив під `http_5` при попередньому виправленні
    # цього ж класу 30.08.2026 — префікс описував КОДИ, а спільним є не код, а те, що
    # розгортання не виносило судження.
    return status.startswith(("http_5", "URLError", "OSError", "TimeoutError", "socket")) or (
        status == "http_429"
    )


def _judge(case: dict[str, Any], answer: dict[str, Any]) -> dict[str, Any]:
    status = str(answer.get("status", ""))
    if _unavailable(status):
        return {
            "id": case["id"],
            "kind": case["kind"],
            "stratum": case["stratum"],
            "status": status,
            "decision_reason": answer.get("decision_reason"),
            "citations": 0,
            "passed": None,
            "unavailable": True,
            "reasons": [f"the deployment did not answer: {status}"],
        }
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

    # A case the deployment never answered is not evidence about the deployment's quality,
    # so it is kept out of every rate and counted on its own line. Nothing is divided by a
    # denominator that includes it.
    unavailable = [result for result in results if result.get("unavailable")]
    judged = [result for result in results if not result.get("unavailable")]

    per_stratum: dict[str, dict[str, int]] = defaultdict(
        lambda: {"cases": 0, "passed": 0, "unavailable": 0}
    )
    per_kind: dict[str, dict[str, int]] = defaultdict(
        lambda: {"cases": 0, "passed": 0, "unavailable": 0}
    )
    for result in results:
        for bucket, key in ((per_stratum, result["stratum"]), (per_kind, result["kind"])):
            if result.get("unavailable"):
                bucket[key]["unavailable"] += 1
                continue
            bucket[key]["cases"] += 1
            bucket[key]["passed"] += int(bool(result["passed"]))

    failures = [result for result in judged if not result["passed"]]
    # UNKNOWN outranks PASS and does not outrank FAIL: a run with unanswered cases cannot
    # be called green, and a run that also failed a judged case has still failed it.
    if failures:
        status = "FAIL"
    elif unavailable:
        status = "UNKNOWN"
    else:
        status = "PASS"
    report = {
        "schema_version": 1,
        "ran_at": datetime.now(UTC).isoformat(),
        "base": arguments.base,
        # Carried so a score is never compared against a run of a different set.
        "reference_set_digest": meta["content_digest"],
        "reference_set_frozen_at": meta["frozen_at"],
        "cases": len(results),
        "judged": len(judged),
        "unavailable": len(unavailable),
        "unavailable_statuses": dict(
            sorted(Counter(str(result["status"]) for result in unavailable).items())
        ),
        "passed": sum(1 for result in judged if result["passed"]),
        "by_kind": {key: value for key, value in sorted(per_kind.items())},
        "retrieval_effectiveness": retrieval_effectiveness(judged),
        "by_stratum": {key: value for key, value in sorted(per_stratum.items())},
        "failures": failures[:40],
        "unavailable_cases": [result["id"] for result in unavailable],
        "status": status,
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
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
