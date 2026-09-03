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
        # Клас доказу мусить збігатися з ОГОЛОШЕНИМ у профілі — у ОБИДВА боки. Гейт,
        # який називає внутрішню кампанію EXTERNAL_INDEPENDENT, відхиляється так само
        # твердо, як відхилявся б внутрішній доказ там, де оголошено зовнішній.
        "redteam.independent": redteam.get("evidence_class")
        == external.get("redteam_evidence_class"),
        "redteam.attestation_verified": bool(redteam.get("attestation_verified"))
        is bool(external.get("redteam_attestation_verified")),
        "redteam.trusted_signer": bool(redteam.get("trusted_signer"))
        is bool(external.get("redteam_trusted_signer_required")),
        "tevv.environment": tevv.get("environment_class")
        in set(external.get("tevv_environment_classes", ())),
        # Доти тут стояло `== "EXTERNAL_INDEPENDENT"` дослівно: політика була вкарбована
        # в КОД і пережила б будь-яку зміну профілю мовчки — саме так і жили дві
        # несумісні політики. Тепер порівнюється оголошене з оголошеним.
        "tevv.independent": tevv.get("independent_class") == external.get("tevv_independent_class"),
        "tevv.trusted_assessor": bool(tevv_checks.get("assessor_trusted_signer"))
        is bool(external.get("tevv_trusted_assessor_required")),
        "postgres.real_backend": postgres.get("backend") == external.get("postgres_backend"),
        "supply_chain.complete": supply.get("completeness")
        == external.get("supply_chain_completeness"),
        "mutation.full_catalogue": mutation.get("scope") == external.get("mutation_scope"),
    }
