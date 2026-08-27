#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.controller_profile import ControllerProfile
from korpus.application.evidence_state import FEATURE_SCHEMA_VERSION, EvidenceState
from korpus.application.predictive_evidence_control import (
    PredictiveEvidenceController,
    RetrievalAction,
)
from pec_common import receipt, sha256_file, write_json
from pec_controller_verify_logic import (
    artifact_errors,
    empty_oracle_report,
    oracle_errors,
    verification_status,
)


def _state_from_features(features: object) -> EvidenceState:
    if not isinstance(features, dict):
        raise TypeError("oracle features must be an object")
    material = dict(features)
    material.setdefault("schema_version", FEATURE_SCHEMA_VERSION)
    return EvidenceState(**material)


def _verify_oracle(profile: ControllerProfile, oracle_path: Path) -> dict[str, object]:
    raw = json.loads(oracle_path.read_text())
    controller = PredictiveEvidenceController(profile, shadow_mode=False)
    eligible_rows = 0
    admitted_rows = 0
    fallback_rows = 0
    mismatches: list[dict[str, str]] = []
    invalid_rows: list[str] = []
    exercised_admitted_leaves: set[str] = set()

    for row in raw.get("decisions", []):
        if row.get("oracle_status") != "PASS":
            continue
        eligible_rows += 1
        query_id = str(row.get("query_id", ""))
        expected = str(row.get("oracle_action", ""))
        try:
            state = _state_from_features(row.get("features"))
            trace = controller.decide(
                state,
                corpus_release_id=profile.corpus_release_id,
                answer_calibration_id=profile.answer_calibration_id,
            )
        except (TypeError, ValueError, KeyError) as exc:
            invalid_rows.append(f"{query_id}:{type(exc).__name__}:{exc}")
            continue

        if trace.effective_action is RetrievalAction.BASELINE:
            fallback_rows += 1
            continue

        admitted_rows += 1
        if trace.leaf_id is not None:
            exercised_admitted_leaves.add(trace.leaf_id)
        actual = trace.effective_action.value
        if actual != expected:
            mismatches.append({"query_id": query_id, "expected": expected, "actual": actual})

    admitted_leaf_ids = {rule.leaf.leaf_id for rule in profile.rules if rule.leaf.admitted}
    unexercised = sorted(admitted_leaf_ids - exercised_admitted_leaves)
    return {
        "oracle_pass_rows": eligible_rows,
        "admitted_rows_checked": admitted_rows,
        "fallback_rows": fallback_rows,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:100],
        "invalid_rows": invalid_rows[:100],
        "admitted_leaf_count": len(admitted_leaf_ids),
        "exercised_admitted_leaf_count": len(exercised_admitted_leaves),
        "unexercised_admitted_leaves": unexercised,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--profile-sha256")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--system-manifest", type=Path, required=True)
    parser.add_argument("--evaluation-protocol", type=Path, required=True)
    parser.add_argument("--replay-receipt", type=Path, required=True)
    parser.add_argument("--training-receipt", type=Path, required=True)
    parser.add_argument("--oracle", type=Path)
    parser.add_argument("--release-gate", action="store_true")
    parser.add_argument(
        "--out", type=Path, default=ROOT / "reports/PEC_CONTROLLER_VERIFY_CURRENT.json"
    )
    args = parser.parse_args()

    profile = ControllerProfile.load(args.profile, args.profile_sha256)
    errors = artifact_errors(profile, args)
    oracle_report = empty_oracle_report(profile)
    if args.oracle is not None:
        oracle_report = _verify_oracle(profile, args.oracle)
        errors.extend(oracle_errors(profile, oracle_report))
    elif args.release_gate:
        errors.append("oracle_receipt_required_for_release_gate")
    status = verification_status(profile, errors)

    report = receipt(
        "pec_controller_verify",
        {
            "status": status,
            "profile_sha256": sha256_file(args.profile),
            "errors": errors,
            **oracle_report,
        },
    )
    write_json(args.out, report)
    print(json.dumps(report, indent=2))
    return 0 if status == "PASS" or (status == "UNKNOWN" and not args.release_gate) else 1
