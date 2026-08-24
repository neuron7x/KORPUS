from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def evaluate_external_requirements(
    external: Mapping[str, Any],
    gates: Mapping[str, Mapping[str, Any]],
) -> dict[str, bool]:
    redteam = gates.get("redteam", {})
    tevv = gates.get("tevv", {})
    tevv_checks = tevv.get("checks", {}) if isinstance(tevv.get("checks"), Mapping) else {}
    postgres = gates.get("postgres_security", {})
    supply = gates.get("supply_chain", {})
    mutation = gates.get("mutation", {})
    return {
        "redteam.independent": redteam.get("evidence_class") == external.get("redteam_evidence_class"),
        "redteam.attestation_verified": redteam.get("attestation_verified") is external.get("redteam_attestation_verified"),
        "redteam.trusted_signer": redteam.get("trusted_signer") is external.get("redteam_trusted_signer_required"),
        "tevv.environment": tevv.get("environment_class") in set(external.get("tevv_environment_classes", ())),
        "tevv.independent": (
            tevv_checks.get("independent_class") is True
            and external.get("tevv_independent_class") == "EXTERNAL_INDEPENDENT"
        ),
        "tevv.trusted_assessor": (
            tevv_checks.get("assessor_trusted_signer") is True
            and external.get("tevv_trusted_assessor_required") is True
        ),
        "postgres.real_backend": postgres.get("backend") == external.get("postgres_backend"),
        "supply_chain.complete": supply.get("completeness") == external.get("supply_chain_completeness"),
        "mutation.full_catalogue": mutation.get("scope") == external.get("mutation_scope"),
    }
