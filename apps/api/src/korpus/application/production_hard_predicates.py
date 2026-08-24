from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HardPredicateState:
    predicate_id: str
    gate: str
    required_proof_class: str
    software_ready: bool
    externally_satisfied: bool
    missing_software_artifacts: tuple[str, ...]
    failed_external_checks: tuple[str, ...]

    @property
    def production_satisfied(self) -> bool:
        return self.software_ready and self.externally_satisfied

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.predicate_id,
            "gate": self.gate,
            "required_proof_class": self.required_proof_class,
            "software_ready": self.software_ready,
            "externally_satisfied": self.externally_satisfied,
            "production_satisfied": self.production_satisfied,
            "missing_software_artifacts": list(self.missing_software_artifacts),
            "failed_external_checks": list(self.failed_external_checks),
        }


@dataclass(frozen=True)
class PredicateRequirement:
    gate: str
    checks: tuple[str, ...]
    metadata_equals: tuple[tuple[str, object], ...] = ()


_REQUIREMENTS: dict[str, PredicateRequirement] = {
    "external_independent_redteam": PredicateRequirement(
        "redteam",
        (
            "report_present", "attestation_present", "attestation_verified", "trusted_signer",
            "source_bound", "release_bound", "independent_class", "preregistered",
            "test_cases_structured", "required_attack_families_covered", "findings_structured",
            "blocking_findings_closed", "declared_status_consistent",
        ),
        (("status", "PASS"),),
    ),
    "live_vulnerability_scanners": PredicateRequirement(
        "supply_chain",
        (
            "security_scanners_executed_clean", "security_scanners_current_commit",
            "container_scanners_executed_clean", "container_scanners_current_commit",
            "container_sboms_valid", "evidence_manifest_bound", "evidence_attestation_verified",
            "evidence_trusted_signer",
        ),
    ),
    "live_postgres_rls": PredicateRequirement(
        "postgres_security",
        ("target_files_present", "grant_contract_static", "postgres_runtime_available", "postgres_adversarial_suite"),
        (("backend", "postgresql"),),
    ),
    "real_domain_corpus_tevv": PredicateRequirement(
        "tevv",
        (
            "evidence_schema", "preregistered", "source_bound", "release_bound",
            "observation_ledger_structured", "null_control_ledger_structured",
            "required_attack_families_covered", "tevv_admissible", "pass_rate",
            "citation_integrity", "leakage", "determinism", "null_controls",
            "null_false_accepts", "attack_families",
        ),
    ),
    "independent_tevv": PredicateRequirement(
        "tevv",
        ("independent_class", "assessor_structured", "assessor_attestation_verified", "assessor_trusted_signer"),
    ),
    "production_like_tevv_environment": PredicateRequirement(
        "tevv", ("environment_class", "assessor_attestation_verified", "assessor_trusted_signer")
    ),
    "production_like_load": PredicateRequirement(
        "reliability",
        (
            "live_load_soak_executed", "load_source_bound", "load_environment",
            "load_slo_steady_p95", "load_slo_cold_start", "load_slo_no_5xx_rated",
            "load_slo_no_subject_throttle_rated", "load_slo_no_retrieval_deadline",
        ),
    ),
    "trusted_load_attestation": PredicateRequirement(
        "reliability", ("load_attestation_verified", "load_trusted_signer")
    ),
    "trusted_recovery_attestation": PredicateRequirement(
        "reliability",
        (
            "recovery_drill_executed", "recovery_source_bound", "recovery_environment",
            "recovery_attestation_verified", "recovery_trusted_signer",
        ),
    ),
    "trusted_hosted_builder": PredicateRequirement(
        "final_release",
        ("builder_provenance_verified", "builder_trusted", "builder_attestation_verified", "builder_trusted_signer"),
    ),
    "trusted_release_signing": PredicateRequirement(
        "final_release", ("release_manifest_bound", "release_attestation_verified", "release_trusted_signer")
    ),
    "exact_python_3_12_13_environment": PredicateRequirement(
        "exact_environment",
        (
            "all_locked_components_installed", "all_versions_exact", "no_unmanaged_distributions",
            "production_python_exact", "lock_hashes_present",
        ),
        (("status", "PASS"),),
    ),
    "pec_human_production_authority": PredicateRequirement("pec_authority", ("evidence_schema", "source_bound", "binding_valid", "audit_trace_nonempty", "training_lineage", "human_judgments", "hosted_evidence", "attestation_verified", "trusted_signer"), (("environment_class", "PRODUCTION"),)),
    "pec_canary_revision_admission": PredicateRequirement("pec_canary", ("authority_pass", "source_bound", "release_bound", "exact_cloud_run_revision", "minimum_samples", "server_error_rate", "human_judgment_admissible"), (("environment_class", "PRODUCTION"),)),
}

def load_hard_predicate_profile(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("hard-predicate profile must be a JSON object")
    predicates = value.get("predicates")
    if not isinstance(predicates, list) or not predicates:
        raise ValueError("hard-predicate profile must contain a non-empty predicates list")
    ids = [str(item.get("id", "")) for item in predicates if isinstance(item, Mapping)]
    if len(ids) != len(predicates) or any(not item for item in ids) or len(ids) != len(set(ids)):
        raise ValueError("hard-predicate IDs must be non-empty and unique")
    if set(ids) != set(_REQUIREMENTS):
        raise ValueError("hard-predicate profile and evaluator predicate sets differ")
    return value

def _all_checks(gate: Mapping[str, Any], names: Sequence[str]) -> tuple[bool, tuple[str, ...]]:
    checks = gate.get("checks", {})
    if not isinstance(checks, Mapping):
        return False, tuple(names)
    failed = tuple(name for name in names if checks.get(name) is not True)
    return not failed, failed


def external_predicate_state(
    predicate_id: str,
    gates: Mapping[str, Mapping[str, Any]],
) -> tuple[bool, tuple[str, ...]]:
    requirement = _REQUIREMENTS.get(predicate_id)
    if requirement is None:
        raise ValueError(f"unknown production hard predicate: {predicate_id}")
    gate = gates.get(requirement.gate, {})
    checks_ok, failed = _all_checks(gate, requirement.checks)
    metadata_failed = tuple(
        f"metadata:{name}"
        for name, expected in requirement.metadata_equals
        if gate.get(name) != expected
    )
    return checks_ok and not metadata_failed, (*failed, *metadata_failed)


def _state(root: Path, raw: Mapping[str, Any], gates: Mapping[str, Mapping[str, Any]]) -> HardPredicateState:
    predicate_id = str(raw.get("id", ""))
    gate = str(raw.get("gate", ""))
    proof = str(raw.get("required_proof_class", ""))
    artifacts = raw.get("software_artifacts", ())
    if not predicate_id or not gate or not proof or not isinstance(artifacts, list):
        raise ValueError(f"invalid hard-predicate record: {predicate_id or '<missing-id>'}")
    requirement = _REQUIREMENTS[predicate_id]
    if gate != requirement.gate:
        raise ValueError(f"hard-predicate gate drift for {predicate_id}: {gate} != {requirement.gate}")
    missing = tuple(str(item) for item in artifacts if not (root / str(item)).is_file())
    external_ok, external_failed = external_predicate_state(predicate_id, gates)
    return HardPredicateState(
        predicate_id=predicate_id,
        gate=gate,
        required_proof_class=proof,
        software_ready=not missing,
        externally_satisfied=external_ok,
        missing_software_artifacts=missing,
        failed_external_checks=external_failed,
    )


def evaluate_hard_predicates(
    root: Path,
    profile: Mapping[str, Any],
    gates: Mapping[str, Mapping[str, Any]],
) -> tuple[HardPredicateState, ...]:
    raw_predicates = profile.get("predicates", ())
    if not isinstance(raw_predicates, list):
        raise ValueError("hard-predicate profile has no predicates list")
    if any(not isinstance(raw, Mapping) for raw in raw_predicates):
        raise ValueError("hard-predicate record must be an object")
    return tuple(_state(root, raw, gates) for raw in raw_predicates)
