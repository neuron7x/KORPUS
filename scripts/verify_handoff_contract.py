from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# `source_digest` is a sibling script, not a package. Added here rather than assumed on
# PYTHONPATH: this module is imported by a test that runs from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from korpus.application.calibration import CalibrationProfile
from korpus.application.retrieval import AUTHORITY_PRIOR, BM25Parameters, RetrievalWeights
from korpus.config import Settings
from source_digest import source_tree_digest
from release_identity import release_tag
ROOT = Path(__file__).resolve().parents[1]
HANDOFF = ROOT / "handoff" / "machine"
def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must contain a JSON object")
    return value


def _release_evidence_state() -> str:
    assurance_path = ROOT / "reports" / "RESEARCH_ASSURANCE_REPORT.json"
    operational_path = ROOT / "reports" / "OPERATIONAL_GATE.json"
    present = (assurance_path.is_file(), operational_path.is_file())
    if present == (False, False):
        return "UNAVAILABLE"
    if present != (True, True):
        raise AssertionError("release evidence is partial; refusing an ambiguous handoff")
    assurance, operational = _load(assurance_path), _load(operational_path)
    if assurance.get("status") != "PASS" or operational.get("production_authorized") is not False:
        raise AssertionError("release evidence is not a fail-closed PASS snapshot")
    promoted_digest = assurance.get("source_tree_sha256")
    if promoted_digest is None or source_tree_digest() != promoted_digest:
        raise AssertionError("release evidence is not bound to this source tree")
    return "BOUND"


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
    release_evidence = _release_evidence_state()
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
            raise AssertionError(
                f"CalibrationProfile default drift: {name}={actual!r}, expected {expected!r}"
            )

    if (
        state["production_authorized"] is not False
        or state.get("canonical_release") != release_tag()
        or state.get("handoff_release") != release_tag()
    ):
        raise AssertionError("handoff production/release identity is inconsistent")
    if gates["production_gate"]["current"] is not False:
        raise AssertionError("production gate must remain false")

    findings = closure["findings"]
    finding_ids = {item["id"] for item in findings}
    if state["audit"]["findings_total"] != len(findings):
        raise AssertionError("finding count drift")
    if state["audit"]["remaining_total"] != len(debt["items"]):
        raise AssertionError("remaining-debt count drift")

    # Both of the numbers above were compared only against each other, and both were
    # stale together: `current_state.json` said OPEN_TECH_DEBT 15 / MITIGATED_LOCAL 33
    # while the closure register said 0 / 44, and this gate — the first prerequisite of
    # `make validate`, which is the first step of `make check` — passed. It loaded the
    # closure two lines earlier and never looked at it.
    #
    # A guard that compares two copies of the same claim proves they agree, not that
    # either is true. The source of truth is the closure register, which is generated
    # from the findings by `build_audit_closure.py`.
    counted = Counter(str(item["v5_status"]) for item in findings)
    declared = {str(key): int(value) for key, value in state["audit"]["status_counts"].items()}
    if declared != dict(counted):
        raise AssertionError(
            f"handoff status counts disagree with the closure register: "
            f"declared {declared}, register {dict(counted)}"
        )
    remaining = sum(
        count for status, count in counted.items() if status != "CLOSED_LOCAL"
    )
    if state["audit"]["remaining_total"] != remaining:
        raise AssertionError(
            f"remaining_total {state['audit']['remaining_total']} disagrees with the "
            f"closure register's {remaining}"
        )

    iteration_items = iterations["items"]
    integration_items = integrations["items"]
    # The status was pinned to PLANNED_NOT_EXECUTED, so the check enforced that the plan
    # stay unexecuted: shipping eight of the ten items would have failed this gate, and
    # the only way past it was to leave the register lying. What the contract needs to
    # hold is that the ten items exist and none of them silently claims to be finished —
    # every acceptance list here ends in evidence from a system nobody in this tree
    # operates, so DONE is not a state this file may reach on its own.
    if iterations["status"] not in {"PLANNED_NOT_EXECUTED", "PARTIALLY_EXECUTED"}:
        raise AssertionError(f"unexpected iteration contract status: {iterations['status']}")
    if len(iteration_items) != 10:
        raise AssertionError("next iteration contract must contain exactly 10 planned items")
    unfinished = {"NOT_EXECUTED", "PARTIALLY_EXECUTED"}
    claimed_done = [
        item["id"]
        for item in iteration_items
        if item.get("status", "NOT_EXECUTED") not in unfinished
    ]
    if claimed_done:
        raise AssertionError(
            f"iterations claim completion inside the repository: {claimed_done}; "
            "every acceptance list ends in external evidence"
        )
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
        raise AssertionError(
            f"planned iterations reference unknown audit findings: {unknown_findings}"
        )

    return {
        "status": "PASS",
        "weights_sum": sum(code_weights.values()),
        "findings_total": len(findings),
        "remaining_debt": len(debt["items"]),
        "next_iterations": len(iteration_items),
        "next_integrations": len(integration_items),
        "production_authorized": False,
        "release_evidence": release_evidence,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), ensure_ascii=False, indent=2, sort_keys=True))
