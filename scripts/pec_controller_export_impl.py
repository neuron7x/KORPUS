#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.controller_profile import (
    ControllerLeaf,
    ControllerProfile,
    ControllerRule,
    FeatureRange,
    RuleCondition,
)
from korpus.application.evidence_state import feature_schema_sha256
from korpus.application.numeric_contracts import finite_number, require_count, require_rate
from pec_common import receipt, sha256_file, write_json


def _load(path: Path) -> dict[str, object]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"artifact must be a JSON object: {path}")
    return raw


def _binding_errors(
    *,
    training: dict[str, object],
    oracle: dict[str, object],
    replay: dict[str, object],
    dataset_sha256: str,
    oracle_sha256: str,
    replay_sha256: str,
    protocol_sha256: str,
    corpus_release_id: str,
    answer_calibration_id: str,
) -> list[str]:
    checks = (
        ("training.dataset_sha256", training.get("dataset_sha256"), dataset_sha256),
        ("training.oracle_sha256", training.get("oracle_sha256"), oracle_sha256),
        ("oracle.replay_sha256", oracle.get("replay_sha256"), replay_sha256),
        ("replay.dataset_sha256", replay.get("dataset_sha256"), dataset_sha256),
        ("replay.corpus_release_id", replay.get("corpus_release_id"), corpus_release_id),
        (
            "replay.evaluation_protocol_sha256",
            replay.get("evaluation_protocol_sha256"),
            protocol_sha256,
        ),
        (
            "replay.answer_calibration_id",
            replay.get("answer_calibration_id"),
            answer_calibration_id,
        ),
    )
    errors: list[str] = []
    for label, actual, expected in checks:
        if not actual:
            errors.append(f"binding_missing:{label}")
        elif str(actual) != expected:
            errors.append(f"binding_mismatch:{label}")
    return errors


def _strict_bool(value: object, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be boolean")
    return value


def _rules(training: dict[str, object]) -> tuple[ControllerRule, ...]:
    rules: list[ControllerRule] = []
    leaves = training.get("leaves", [])
    if not isinstance(leaves, (list, tuple)):
        raise ValueError("training leaves must be a list")
    for item in leaves:
        if not isinstance(item, dict):
            raise ValueError("training leaf must be an object")
        rules.append(
            ControllerRule(
                rule_id=f"rule-{item['leaf_id']}",
                conditions=tuple(
                    RuleCondition.model_validate(condition) for condition in item["conditions"]
                ),
                leaf=ControllerLeaf(
                    leaf_id=str(item["leaf_id"]),
                    action=item["action"],
                    admitted=_strict_bool(item["admitted"], label="leaf admitted"),
                    observed_samples=require_count(
                        item["calibration_samples"], label="leaf calibration_samples"
                    ),
                    upper_error_bound=_strict_rate(
                        item["upper_error_bound"], label="leaf upper_error_bound"
                    ),
                    support={
                        key: FeatureRange.model_validate(value)
                        for key, value in dict(item["support"]).items()
                    },
                ),
            )
        )
    return tuple(rules)


def _strict_rate(value: object, *, label: str) -> float:
    if not finite_number(value):
        raise ValueError(f"{label} must be a finite numeric value")
    return require_rate(value, label=label)


def _strict_open_unit_rate(value: object, *, label: str) -> float:
    rate = _strict_rate(value, label=label)
    if not 0.0 < rate < 1.0:
        raise ValueError(f"{label} must be strictly inside (0, 1)")
    return rate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--training", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--system-manifest", type=Path, required=True)
    parser.add_argument("--evaluation-protocol", type=Path, required=True)
    parser.add_argument("--replay-receipt", type=Path, required=True)
    parser.add_argument("--corpus-release-id", required=True)
    parser.add_argument("--answer-calibration-id", required=True)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "config/pec/controller-profile.json")
    parser.add_argument(
        "--receipt", type=Path, default=ROOT / "reports/PEC_CONTROLLER_EXPORT_CURRENT.json"
    )
    parser.add_argument("--release-gate", action="store_true")
    args = parser.parse_args()

    training = _load(args.training)
    oracle = _load(args.oracle)
    replay = _load(args.replay_receipt)
    dataset_digest = sha256_file(args.dataset)
    oracle_digest = sha256_file(args.oracle)
    replay_digest = sha256_file(args.replay_receipt)
    protocol_digest = sha256_file(args.evaluation_protocol)
    errors = _binding_errors(
        training=training,
        oracle=oracle,
        replay=replay,
        dataset_sha256=dataset_digest,
        oracle_sha256=oracle_digest,
        replay_sha256=replay_digest,
        protocol_sha256=protocol_digest,
        corpus_release_id=args.corpus_release_id,
        answer_calibration_id=args.answer_calibration_id,
    )
    for name, raw in (("training", training), ("oracle", oracle), ("replay", replay)):
        status = str(raw.get("status", "UNKNOWN"))
        if status == "FAIL":
            errors.append(f"upstream_fail:{name}")

    rules = _rules(training)
    upstream_pass = all(
        str(raw.get("status", "UNKNOWN")) == "PASS" for raw in (training, oracle, replay)
    )
    admitted = any(rule.leaf.admitted for rule in rules)
    status = "FAIL" if errors else ("PASS" if upstream_pass and admitted else "UNKNOWN")

    profile = ControllerProfile(
        profile_id=args.profile_id,
        dataset_sha256=dataset_digest,
        system_manifest_sha256=sha256_file(args.system_manifest),
        evaluation_protocol_sha256=protocol_digest,
        replay_receipt_sha256=replay_digest,
        training_receipt_sha256=sha256_file(args.training),
        feature_schema_sha256=feature_schema_sha256(),
        corpus_release_id=args.corpus_release_id,
        answer_calibration_id=args.answer_calibration_id,
        admission_status=status,
        controller_risk_limit=_strict_open_unit_rate(
            training.get("controller_risk_limit", 0.5), label="controller_risk_limit"
        ),
        minimum_leaf_samples=require_count(
            training.get("minimum_leaf_samples", 1),
            positive=True,
            label="minimum_leaf_samples",
        ),
        rules=rules,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(profile.canonical_json() + "\n", encoding="utf-8")
    report = receipt(
        "pec_controller_export",
        {
            "status": status,
            "profile": str(args.out.relative_to(ROOT))
            if args.out.is_relative_to(ROOT)
            else str(args.out),
            "profile_sha256": sha256_file(args.out),
            "profile_semantic_digest": profile.digest,
            "dataset_sha256": dataset_digest,
            "oracle_sha256": oracle_digest,
            "replay_sha256": replay_digest,
            "training_sha256": sha256_file(args.training),
            "evaluation_protocol_sha256": protocol_digest,
            "corpus_release_id": args.corpus_release_id,
            "answer_calibration_id": args.answer_calibration_id,
            "admitted_leaves": sum(rule.leaf.admitted for rule in rules),
            "total_leaves": len(rules),
            "errors": sorted(set(errors)),
        },
    )
    write_json(args.receipt, report)
    print(json.dumps(report, indent=2))
    return 0 if status == "PASS" or (status == "UNKNOWN" and not args.release_gate) else 1
