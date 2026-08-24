"""Composable verification predicates for exported PEC controller profiles."""

from __future__ import annotations

from pec_common import sha256_file


def artifact_errors(profile, args) -> list[str]:
    errors: list[str] = []
    try:
        profile.validate_artifact_bindings(
            dataset=args.dataset,
            system_manifest=args.system_manifest,
            evaluation_protocol=args.evaluation_protocol,
            replay_receipt=args.replay_receipt,
        )
    except ValueError as exc:
        errors.append(str(exc))
    if not args.training_receipt.is_file():
        errors.append("PEC training receipt artifact is missing")
    elif sha256_file(args.training_receipt) != profile.training_receipt_sha256:
        errors.append("PEC training receipt digest mismatch")
    return errors


def empty_oracle_report(profile) -> dict[str, object]:
    return {
        "oracle_pass_rows": 0,
        "admitted_rows_checked": 0,
        "fallback_rows": 0,
        "mismatch_count": 0,
        "mismatches": [],
        "invalid_rows": [],
        "admitted_leaf_count": sum(rule.leaf.admitted for rule in profile.rules),
        "exercised_admitted_leaf_count": 0,
        "unexercised_admitted_leaves": [],
    }


def oracle_errors(profile, report: dict[str, object]) -> list[str]:
    errors: list[str] = []
    if report["invalid_rows"]:
        errors.append("oracle_contains_invalid_feature_rows")
    if int(report["mismatch_count"]) > 0:
        errors.append("promoted_controller_oracle_mismatch")
    admitted_profile = profile.admission_status == "PASS" and int(report["admitted_leaf_count"]) > 0
    if admitted_profile and int(report["admitted_rows_checked"]) == 0:
        errors.append("no_promoted_controller_decision_was_reproduced")
    if admitted_profile and report["unexercised_admitted_leaves"]:
        errors.append("admitted_leaves_not_exercised_by_oracle")
    return errors


def verification_status(profile, errors: list[str]) -> str:
    if errors:
        return "FAIL"
    return "PASS" if profile.admission_status == "PASS" else "UNKNOWN"
