from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, cast

from korpus.application.junit_contracts import junit_counts
from korpus.application.release_claim_admission import canonical_paths_admitted
from korpus.application.release_claim_common import (
    EvidenceContext,
    file_sha256,
    integer,
    load_object,
)
from korpus.application.release_claim_hosted_contract import hosted_execution_admitted

EXPECTED_CHECKS = {
    "profile_gate_id",
    "evidence_class_internal_adversarial",
    "attack_families_nonempty",
    "attack_families_unique",
    "pytest_targets_nonempty",
    "pytest_targets_unique",
    "pytest_targets_exist",
    "family_target_mapping_complete",
    "every_family_has_executable_target",
    "family_targets_declared_in_suite",
    "family_targets_exist",
    "pytest_exit_zero",
    "tests_executed",
    "no_test_failures",
    "no_test_errors",
    "no_test_skips",
}


def _profile_contract(profile: dict[str, Any], root: Path) -> bool:
    families, targets, mapping = (
        profile.get("attack_families"),
        profile.get("pytest_targets"),
        profile.get("family_targets"),
    )
    if (
        not isinstance(families, list)
        or not isinstance(targets, list)
        or not isinstance(mapping, dict)
    ):
        return False
    if (
        not families
        or not targets
        or not all(isinstance(item, str) for item in [*families, *targets])
    ):
        return False
    if not all(isinstance(mapping.get(family), list) and mapping[family] for family in families):
        return False
    mapped = [item for family in families for item in mapping.get(family, [])]
    return (
        len(set(families)) == len(families)
        and len(set(targets)) == len(targets)
        and set(mapping) == set(families)
        and set(mapped) == set(targets)
        and all((root / target).is_file() for target in targets)
    )


def _junit_matches(payload: dict[str, Any], context: EvidenceContext) -> bool:
    path = context.root / f"reports/release/{context.release}/INFERENCE_SECURITY_GATE.junit.xml"
    try:
        observed = cast(dict[str, int], junit_counts(ET.parse(path).getroot()))
    except (OSError, ET.ParseError, ValueError):
        return False
    declared = payload.get("pytest")
    return (
        payload.get("junit_sha256") == file_sha256(path)
        and isinstance(declared, dict)
        and declared == observed
    )


def _identity(payload: dict[str, Any], profile: dict[str, Any], profile_path: Path) -> bool:
    return (
        payload.get("schema") == "korpus.production-gate.v1"
        and payload.get("gate_id") == "inference_security"
        and payload.get("evidence_class") == "INTERNAL_ADVERSARIAL"
        and payload.get("status") == "PASS"
        and payload.get("profile") == "config/assurance/inference-security-v1.json"
        and payload.get("profile_sha256") == file_sha256(profile_path)
        and payload.get("attack_families") == profile["attack_families"]
        and payload.get("pytest_targets") == profile["pytest_targets"]
    )


def inference_evidence(payload: dict[str, Any], context: EvidenceContext) -> bool:
    profile_path = context.root / "config/assurance/inference-security-v1.json"
    profile = load_object(profile_path)
    checks, counts = payload.get("checks"), payload.get("pytest")
    if profile is None or not _profile_contract(profile, context.root):
        return False
    targets = profile["pytest_targets"]
    junit_relative = f"reports/release/{context.release}/INFERENCE_SECURITY_GATE.junit.xml"
    inputs = [
        "config/assurance/inference-security-v1.json",
        "scripts/run_inference_security_gate.py",
        junit_relative,
        *targets,
    ]
    if (
        not canonical_paths_admitted(context.root, inputs)
        or not _identity(payload, profile, profile_path)
        or not isinstance(checks, dict)
        or set(checks) != EXPECTED_CHECKS
        or not all(value is True for value in checks.values())
        or payload.get("failures") != []
        or payload.get("pytest_exit_code") != 0
        or not isinstance(counts, dict)
    ):
        return False
    return (
        integer(counts.get("tests"), minimum=1)
        and counts.get("failures") == counts.get("errors") == counts.get("skipped") == 0
        and _junit_matches(payload, context)
        and hosted_execution_admitted(context, [context.evidence, junit_relative], counts)
    )
