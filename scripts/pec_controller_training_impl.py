#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.numeric_contracts import finite_number, require_count, require_rate
from korpus.application.pec_training import (
    TrainingRow,
    hoeffding_upper,
    nested_group_validation,
    select_hyperparameters,
    train_tree,
)
from pec_common import read_jsonl, receipt, sha256_file, write_json


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--delta", type=float, default=0.05)
    parser.add_argument("--risk-limit", type=float, required=True)
    parser.add_argument("--minimum-leaf-samples", type=int, default=30)
    parser.add_argument("--release-gate", action="store_true")
    parser.add_argument(
        "--out", type=Path, default=ROOT / "reports/PEC_CONTROLLER_TRAINING_CURRENT.json"
    )
    return parser.parse_args()


def _validate_arguments(args: argparse.Namespace) -> None:
    delta = require_rate(args.delta, label="delta")
    if not 0.0 < delta < 1.0:
        raise ValueError("delta must be strictly inside (0, 1)")
    risk_limit = require_rate(args.risk_limit, label="risk-limit")
    if not 0.0 < risk_limit < 1.0:
        raise ValueError("risk-limit must be strictly inside (0, 1)")
    require_count(args.minimum_leaf_samples, positive=True, label="minimum-leaf-samples")


def _decisions(path: Path) -> dict[str, dict]:
    raw = json.loads(path.read_text())
    return {
        str(item["query_id"]): item
        for item in raw.get("decisions", [])
        if item.get("oracle_status") == "PASS"
    }


def _training_rows(dataset: dict[str, dict], decisions: dict[str, dict]) -> list[TrainingRow]:
    rows: list[TrainingRow] = []
    for query_id, decision in decisions.items():
        meta = dataset.get(query_id)
        if meta and meta.get("partition") == "train":
            rows.append(
                TrainingRow(
                    query_id,
                    str(meta["group_id"]),
                    dict(decision["features"]),
                    str(decision["oracle_action"]),
                )
            )
    return rows


def _calibration_rows(
    dataset: dict[str, dict], decisions: dict[str, dict]
) -> list[tuple[dict, dict]]:
    return [
        (meta, decision)
        for query_id, decision in decisions.items()
        if (meta := dataset.get(query_id)) is not None and meta.get("partition") == "calibration"
    ]


def _leaf_stats(model: object, calibration: list[tuple[dict, dict]]) -> dict[str, dict]:
    stats = {leaf.leaf_id: {"samples": 0, "errors": 0, "support": {}} for leaf in model.leaves}
    for _, decision in calibration:
        leaf = model.predict_leaf(dict(decision["features"]))
        if leaf is None:
            continue
        state = stats[leaf.leaf_id]
        state["samples"] += 1
        state["errors"] += int(leaf.action != str(decision["oracle_action"]))
        _update_support(state["support"], decision["features"])
    return stats


def _update_support(support: dict[str, list[float]], features: dict) -> None:
    for name, value in features.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        if not finite_number(value):
            raise ValueError(f"PEC calibration feature {name!r} must be finite")
        number = float(value)
        bounds = support.setdefault(name, [number, number])
        bounds[0], bounds[1] = min(bounds[0], number), max(bounds[1], number)


def _export_leaves(model: object, stats: dict[str, dict], args: argparse.Namespace) -> list[dict]:
    leaves: list[dict] = []
    for leaf in model.leaves:
        state = stats[leaf.leaf_id]
        upper = hoeffding_upper(int(state["errors"]), int(state["samples"]), args.delta)
        admitted = state["samples"] >= args.minimum_leaf_samples and upper <= args.risk_limit
        leaves.append(
            {
                "leaf_id": leaf.leaf_id,
                "conditions": [condition.model_dump(mode="json") for condition in leaf.conditions],
                "action": leaf.action,
                "training_samples": leaf.training_samples,
                "calibration_samples": state["samples"],
                "calibration_errors": state["errors"],
                "upper_error_bound": upper,
                "admitted": admitted,
                "support": {
                    name: {"minimum": bounds[0], "maximum": bounds[1]}
                    for name, bounds in state["support"].items()
                },
            }
        )
    return leaves


def main() -> int:
    args = _arguments()
    _validate_arguments(args)
    dataset = {str(row["id"]): row for row in read_jsonl(args.dataset)}
    decisions = _decisions(args.oracle)
    rows = _training_rows(dataset, decisions)
    if not rows:
        raise SystemExit("no PASS train oracle rows")
    nested = nested_group_validation(rows)
    depth, min_leaf, cv = select_hyperparameters(rows)
    model = train_tree(rows, max_depth=depth, min_leaf=min_leaf)
    calibration = _calibration_rows(dataset, decisions)
    leaves = _export_leaves(model, _leaf_stats(model, calibration), args)
    status = (
        "PASS"
        if any(leaf["admitted"] for leaf in leaves) and nested["status"] == "PASS"
        else "UNKNOWN"
    )
    report = receipt(
        "pec_controller_training",
        {
            "status": status,
            "dataset_sha256": sha256_file(args.dataset),
            "oracle_sha256": sha256_file(args.oracle),
            "train_rows": len(rows),
            "calibration_rows": len(calibration),
            "selected": {"max_depth": depth, "min_leaf": min_leaf, **cv},
            "nested_generalization": nested,
            "confidence_delta": args.delta,
            "controller_risk_limit": args.risk_limit,
            "minimum_leaf_samples": args.minimum_leaf_samples,
            "leaves": leaves,
        },
    )
    write_json(args.out, report)
    print(json.dumps({key: value for key, value in report.items() if key != "leaves"}, indent=2))
    return 0 if status == "PASS" or (status == "UNKNOWN" and not args.release_gate) else 1
