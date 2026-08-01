from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from korpus.application.calibration import CalibrationProfile
from korpus.application.retrieval import AUTHORITY_PRIOR, BM25Parameters, RetrievalWeights
from korpus.config import Settings

ROOT = Path(__file__).resolve().parents[1]
HANDOFF = ROOT / "handoff" / "machine"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must contain a JSON object")
    return value


def verify() -> dict[str, Any]:
    required = [
        ROOT / "handoff" / "START_HERE_UA.md",
        ROOT / "handoff" / "SSOT_AND_PROVENANCE.md",
        HANDOFF / "current_state.json",
        HANDOFF / "calibration_weights.json",
        HANDOFF / "next_iterations.json",
        HANDOFF / "next_integrations.json",
        HANDOFF / "acceptance_gates.json",
        ROOT / "handoff" / "prompts" / "CLAUDE_CODE_MASTER_PROMPT.md",
        ROOT / "handoff" / "prompts" / "CODEX_MASTER_PROMPT.md",
        ROOT / "handoff" / "prompts" / "VERIFIER_PROMPT.md",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        raise AssertionError(f"missing handoff files: {missing}")

    state = _load(HANDOFF / "current_state.json")
    weights_doc = _load(HANDOFF / "calibration_weights.json")
    iterations = _load(HANDOFF / "next_iterations.json")
    integrations = _load(HANDOFF / "next_integrations.json")
    gates = _load(HANDOFF / "acceptance_gates.json")
    assurance = _load(ROOT / "reports" / "RESEARCH_ASSURANCE_REPORT.json")
    operational = _load(ROOT / "reports" / "OPERATIONAL_GATE.json")
    closure = _load(ROOT / "docs" / "audit" / "closure" / "KORPUS_v5_FINDINGS_CLOSURE.json")
    debt = _load(ROOT / "docs" / "audit" / "closure" / "KORPUS_v5_REMAINING_DEBT.json")

    code_weights = RetrievalWeights().as_dict()
    if weights_doc["retrieval_weights"] != code_weights:
        raise AssertionError("handoff retrieval weights differ from code defaults")
    if not math.isclose(sum(code_weights.values()), 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise AssertionError("retrieval weights do not sum to one")

    bm25 = BM25Parameters()
    if weights_doc["bm25"] != {"k1": bm25.k1, "b": bm25.b}:
        raise AssertionError("handoff BM25 parameters differ from code defaults")

    authority = {key.value: value for key, value in AUTHORITY_PRIOR.items()}
    if weights_doc["authority_priors"] != authority:
        raise AssertionError("handoff authority priors differ from code defaults")

    settings = Settings(_env_file=None)
    runtime = weights_doc["development_answer_gates"]
    if runtime["minimum_retrieval_score"] != settings.min_retrieval_score:
        raise AssertionError("minimum retrieval score drift")
    if runtime["minimum_query_coverage_runtime_default"] != settings.min_query_coverage:
        raise AssertionError("minimum query coverage drift")
    if runtime["minimum_support_score"] != settings.min_support_score:
        raise AssertionError("minimum support score drift")
    selection = weights_doc["selection"]
    if selection["candidate_budget"] != settings.retrieval_candidate_budget:
        raise AssertionError("candidate budget drift")
    if selection["retrieval_timeout_ms"] != settings.retrieval_timeout_ms:
        raise AssertionError("retrieval timeout drift")
    if settings.semantic_weight != 0.0 or weights_doc["retrieval_weights"]["semantic"] != 0.0:
        raise AssertionError("semantic retrieval must remain disabled without a bound profile")

    # Verify CalibrationProfile defaults without fabricating a valid production profile.
    profile_fields = CalibrationProfile.model_fields
    expected_profile_defaults = {
        "bm25_k1": weights_doc["bm25"]["k1"],
        "bm25_b": weights_doc["bm25"]["b"],
        "weight_lexical": code_weights["lexical"],
        "weight_semantic": code_weights["semantic"],
        "weight_query_coverage": code_weights["query_coverage"],
        "weight_character": code_weights["character"],
        "weight_authority": code_weights["authority"],
        "weight_phrase": code_weights["phrase"],
        "weight_temporal": code_weights["temporal"],
        "diversity_lambda": selection["diversity_lambda"],
        "per_version_cap": selection["per_version_cap"],
        "retrieval_candidate_budget": selection["candidate_budget"],
        "retrieval_timeout_ms": selection["retrieval_timeout_ms"],
    }
    for name, expected in expected_profile_defaults.items():
        actual = profile_fields[name].default
        if actual != expected:
            raise AssertionError(f"CalibrationProfile default drift: {name}={actual!r}, expected {expected!r}")

    if state["base_source_tree_sha256"] != assurance["source_tree_sha256"]:
        raise AssertionError("handoff source digest differs from assurance report")
    if state["production_authorized"] is not False or operational["production_authorized"] is not False:
        raise AssertionError("handoff must not claim production authorization")
    if gates["production_gate"]["current"] is not False:
        raise AssertionError("production gate must remain false")

    findings = closure["findings"]
    finding_ids = {item["id"] for item in findings}
    if state["audit"]["findings_total"] != len(findings):
        raise AssertionError("finding count drift")
    if state["audit"]["remaining_total"] != len(debt["items"]):
        raise AssertionError("remaining-debt count drift")

    iteration_items = iterations["items"]
    integration_items = integrations["items"]
    if iterations["status"] != "PLANNED_NOT_EXECUTED" or len(iteration_items) != 10:
        raise AssertionError("next iteration contract must contain exactly 10 planned items")
    if integrations["status"] != "PLANNED_NOT_EXECUTED" or len(integration_items) != 7:
        raise AssertionError("next integration contract must contain exactly 7 planned items")
    if len({item["id"] for item in iteration_items}) != 10:
        raise AssertionError("duplicate iteration IDs")
    if len({item["id"] for item in integration_items}) != 7:
        raise AssertionError("duplicate integration IDs")
    unknown_findings = sorted(
        finding_id
        for item in iteration_items
        for finding_id in item.get("findings", [])
        if finding_id not in finding_ids
    )
    if unknown_findings:
        raise AssertionError(f"planned iterations reference unknown audit findings: {unknown_findings}")

    return {
        "status": "PASS",
        "weights_sum": sum(code_weights.values()),
        "findings_total": len(findings),
        "remaining_debt": len(debt["items"]),
        "next_iterations": len(iteration_items),
        "next_integrations": len(integration_items),
        "production_authorized": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), ensure_ascii=False, indent=2, sort_keys=True))
