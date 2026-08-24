#!/usr/bin/env python3
"""Run PEC scientific gates without converting synthetic evidence into production authority."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.pec_research import (
    conditional_risk_report, feature_ablation_generalization, observed_information_gain,
    production_judgment_validity, replay_priority_enrichment, research_status,
)
from korpus.application.pec_training import TrainingRow
from pec_common import read_jsonl, receipt, sha256_file, write_json
from pec_research_cli_logic import load_optional_report


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--oracle", type=Path)
    parser.add_argument("--risk-limit", type=float, default=0.05)
    parser.add_argument("--delta", type=float, default=0.05)
    parser.add_argument("--minimum-stratum-samples", type=int, default=30)
    parser.add_argument("--release-gate", action="store_true")
    parser.add_argument("--out", type=Path, default=ROOT / "reports/PEC_RESEARCH_PROGRAM_CURRENT.json")
    return parser.parse_args()


def _oracle_training_rows(dataset: list[dict], oracle: dict) -> list[TrainingRow]:
    metadata = {str(row["id"]): row for row in dataset}
    output: list[TrainingRow] = []
    for decision in oracle.get("decisions", []):
        query_id = str(decision.get("query_id", "")); meta = metadata.get(query_id)
        if decision.get("oracle_status") != "PASS" or meta is None or meta.get("partition") != "train":
            continue
        output.append(TrainingRow(
            query_id, str(meta.get("group_id", "")), dict(decision.get("features", {})),
            str(decision.get("oracle_action", "")),
        ))
    return output


def main() -> int:
    args = _args(); dataset = read_jsonl(args.dataset)
    validity = production_judgment_validity(dataset)
    _, replay_rows, replay_digest = load_optional_report(args.replay, "observations")
    oracle_raw, _, oracle_digest = load_optional_report(args.oracle, "decisions")
    risk_rows = [
        {"risk_class": row.get("risk_class", ""), "answer_error": bool(row.get("answer_error"))}
        for row in replay_rows if row.get("risk_class")
    ]
    conditional = conditional_risk_report(
        risk_rows, stratum_key="risk_class", error_key="answer_error",
        risk_limit=args.risk_limit, delta=args.delta, minimum_samples=args.minimum_stratum_samples,
    ) if risk_rows else {"status": "UNKNOWN", "reason": "no_replay_risk_rows"}
    training_rows = _oracle_training_rows(dataset, oracle_raw) if oracle_raw else []
    generalization = feature_ablation_generalization(training_rows)
    priority = replay_priority_enrichment(replay_rows) if replay_rows else {"status": "UNKNOWN", "reason": "no_replay_rows"}
    information_gain = observed_information_gain(replay_rows) if replay_rows else {"status": "UNKNOWN", "reason": "no_replay_rows"}
    status, scientific_authority = research_status(
        validity, [conditional, generalization, priority, information_gain]
    )
    report = receipt("pec_research_program", {
        "status": status, "scientific_authority": "PRODUCTION_JUDGED" if scientific_authority else "NONE",
        "dataset_sha256": sha256_file(args.dataset), "replay_sha256": replay_digest, "oracle_sha256": oracle_digest,
        "production_judgment_validity": validity, "conditional_risk": conditional,
        "feature_generalization": generalization, "replay_priority": priority,
        "observed_information_gain": information_gain,
    })
    write_json(args.out, report); print(json.dumps({k:v for k,v in report.items() if k not in {"feature_generalization","observed_information_gain"}}, indent=2))
    return 0 if status == "PASS" or (status == "UNKNOWN" and not args.release_gate) else 1


if __name__ == "__main__":
    raise SystemExit(main())
