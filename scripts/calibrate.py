#!/usr/bin/env python3
"""Calibrate the retrieval threshold against the eval set, and freeze the result.

The threshold decides when the system speaks and when it stays silent. Picking it by
feel is how a number nobody can defend ends up governing an answer, so it is chosen
by a stated rule over a stated dataset:

    among the thresholds that keep every refusal a refusal, disclose nothing, and
    still answer every case the reviewers marked answerable, take the highest.

Highest, not best-scoring: between two thresholds with identical outcomes, the
stricter one abstains sooner on the questions the eval set does not cover.

The result is frozen into config/calibration.json together with the hash of the
dataset it was derived from. `--verify` recomputes and fails if the recorded numbers
no longer reproduce — a calibration that silently drifts is worse than none, because
it still looks measured.

    python3 scripts/calibrate.py            # recompute and write
    python3 scripts/calibrate.py --verify   # reproduce and compare (used by CI)
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
sys.path.insert(0, str(ROOT / "scripts"))

from korpus.application.answer_query import AnswerPolicy, AnswerQuery  # noqa: E402
from korpus.domain.access import Principal  # noqa: E402
from korpus.domain.models import AccessTier, AnswerStatus, Query  # noqa: E402
from korpus.infrastructure.in_memory import FixedClock, InMemoryAuditSink  # noqa: E402
from korpus.infrastructure.lexical import LexicalRetriever  # noqa: E402
from run_evals import CLOCK, GENERATORS, build_span, load, stable_uuid  # noqa: E402

DATASET = ROOT / "evals/datasets/seed.jsonl"
OUTPUT = ROOT / "config/calibration.json"
GRID = [round(0.50 + 0.02 * step, 2) for step in range(26)]  # 0.50 … 1.00


@dataclass
class Outcome:
    threshold: float
    matched: int
    total: int
    disclosures: int
    missed_answers: int
    false_answers: int

    @property
    def usable(self) -> bool:
        """No disclosure, no answer that should have been a refusal, nothing missed."""
        return self.disclosures == 0 and self.false_answers == 0 and self.missed_answers == 0


async def evaluate(threshold: float, cases: list[dict[str, Any]]) -> Outcome:
    matched = disclosures = missed = false_answers = 0
    for case in cases:
        case_id = str(case["id"])
        spans = [build_span(case_id, entry) for entry in case.get("corpus", [])]
        granted = frozenset(
            stable_uuid(f"{case_id}:{entry.get('corpus', 'default')}")
            for entry in case.get("corpus", [])
            if entry.get("granted", True)
        )
        principal = Principal(
            subject_id="calibration",
            tier=AccessTier(case.get("principal", {}).get("tier", "public")),
            authorized_corpora=granted,
        )
        service = AnswerQuery(
            retriever=LexicalRetriever(spans),
            generator=GENERATORS[case.get("generator", "stub")](),
            audit=InMemoryAuditSink(),
            policy=AnswerPolicy(minimum_score=threshold),
            clock=FixedClock(CLOCK),
        )
        requested = [stable_uuid("unheld")] if case.get("request_unheld_corpus") else []
        answer = await service.execute(
            Query(text=str(case["query"]), corpus_ids=requested), principal
        )
        expected = AnswerStatus(str(case["expected_status"]))
        if answer.status is expected:
            matched += 1
        elif expected is AnswerStatus.ANSWERED:
            missed += 1
        elif answer.status is AnswerStatus.ANSWERED:
            false_answers += 1
        forbidden = case.get("forbidden_text")
        if forbidden and str(forbidden) in answer.model_dump_json():
            disclosures += 1
    return Outcome(threshold, matched, len(cases), disclosures, missed, false_answers)


def dataset_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def calibrate() -> dict[str, Any]:
    cases = load(DATASET)
    outcomes = [await evaluate(threshold, cases) for threshold in GRID]
    usable = [outcome for outcome in outcomes if outcome.usable]
    if not usable:
        raise SystemExit(
            "no threshold satisfies the rule on this dataset — the corpus, the "
            "fixtures or the policy must change before a number can be defended"
        )
    chosen = max(usable, key=lambda outcome: outcome.threshold)
    return {
        "min_retrieval_score": chosen.threshold,
        "rule": (
            "highest threshold with zero disclosures, zero answers that should have "
            "been refusals, and zero missed answerable cases"
        ),
        "dataset": str(DATASET.relative_to(ROOT)),
        "dataset_sha256": dataset_digest(DATASET),
        "cases": chosen.total,
        "matched": chosen.matched,
        "usable_range": [min(o.threshold for o in usable), max(o.threshold for o in usable)],
        "grid": [
            {
                "threshold": outcome.threshold,
                "matched": outcome.matched,
                "disclosures": outcome.disclosures,
                "missed_answers": outcome.missed_answers,
                "false_answers": outcome.false_answers,
            }
            for outcome in outcomes
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true", help="reproduce and compare")
    args = parser.parse_args()

    computed = asyncio.run(calibrate())

    if not args.verify:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(
            json.dumps(computed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps({k: computed[k] for k in ("min_retrieval_score", "usable_range",
                                                   "matched", "cases")}, indent=2))
        return 0

    if not OUTPUT.exists():
        print("FAIL: no frozen calibration to verify", file=sys.stderr)
        return 2
    frozen = json.loads(OUTPUT.read_text(encoding="utf-8"))
    differences = [
        key
        for key in ("min_retrieval_score", "dataset_sha256", "cases", "matched", "grid")
        if frozen.get(key) != computed[key]
    ]
    if differences:
        print(f"FAIL: calibration no longer reproduces: {differences}", file=sys.stderr)
        print(
            f"  frozen threshold={frozen.get('min_retrieval_score')} "
            f"recomputed={computed['min_retrieval_score']}",
            file=sys.stderr,
        )
        return 1
    print(
        f"calibration reproduces: threshold={frozen['min_retrieval_score']} "
        f"over {frozen['cases']} cases, dataset {frozen['dataset_sha256'][:12]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
