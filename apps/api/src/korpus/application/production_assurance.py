from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProductionAssuranceVerdict:
    status: str
    checks: Mapping[str, bool]
    failures: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


def evaluate_production_assurance(
    profile: Mapping[str, Any],
    gates: Mapping[str, Mapping[str, Any]],
    *,
    source_digest: str,
    release: str,
) -> ProductionAssuranceVerdict:
    required = tuple(str(item) for item in profile.get("required_gates", ()))
    external = profile.get("external_requirements", {})
    checks: dict[str, bool] = {}
    for gate_id in required:
        gate = gates.get(gate_id, {})
        checks[f"{gate_id}.present"] = bool(gate)
        checks[f"{gate_id}.pass"] = gate.get("status") == "PASS"
        checks[f"{gate_id}.source_bound"] = gate.get("source_tree_sha256") == source_digest
        checks[f"{gate_id}.release_bound"] = gate.get("release") == release

    redteam = gates.get("redteam", {})
    checks["redteam.independent"] = redteam.get("evidence_class") == external.get("redteam_evidence_class")
    checks["redteam.attestation_verified"] = redteam.get("attestation_verified") is external.get("redteam_attestation_verified")
    checks["redteam.trusted_signer"] = redteam.get("trusted_signer") is external.get("redteam_trusted_signer_required")
    tevv = gates.get("tevv", {})
    allowed_envs = set(external.get("tevv_environment_classes", ()))
    checks["tevv.environment"] = tevv.get("environment_class") in allowed_envs
    postgres = gates.get("postgres_security", {})
    checks["postgres.real_backend"] = postgres.get("backend") == external.get("postgres_backend")
    supply = gates.get("supply_chain", {})
    checks["supply_chain.complete"] = supply.get("completeness") == external.get("supply_chain_completeness")
    mutation = gates.get("mutation", {})
    checks["mutation.full_catalogue"] = mutation.get("scope") == external.get("mutation_scope")

    failures = tuple(name for name, passed in checks.items() if not passed)
    return ProductionAssuranceVerdict("PASS" if not failures else "FAIL", checks, failures)


def gate_payload(
    gate_id: str,
    *,
    status: str,
    source_digest: str,
    release: str,
    checks: Mapping[str, bool],
    failures: Sequence[str] = (),
    **metadata: Any,
) -> dict[str, Any]:
    return {
        "schema": "korpus.production-gate.v1",
        "gate_id": gate_id,
        "status": status,
        "source_tree_sha256": source_digest,
        "release": release,
        "checks": dict(checks),
        "failures": list(failures),
        **metadata,
    }
