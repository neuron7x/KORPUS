"""Semantics-preserving PEC metamorphic invariants."""

from __future__ import annotations

from korpus.application.numeric_contracts import strict_int

ABSTAIN_OR_REVIEW = {"insufficient_evidence", "requires_human_review"}


def metamorphic_issues(base: dict[str, object], transformed: dict[str, object]) -> list[str]:
    issues: list[str] = []
    if transformed.get("semantics_validated") is not True:
        issues.append("transformation_not_semantically_validated")
    if transformed.get("authorization_decision") != base.get("authorization_decision"):
        issues.append("authorization_changed")

    base_risk, transformed_risk = base.get("risk_rank"), transformed.get("risk_rank")
    if not strict_int(base_risk) or not strict_int(transformed_risk):
        issues.append("invalid_risk_rank")
    elif transformed_risk < base_risk:
        issues.append("risk_class_weakened")

    base_authority, transformed_authority = (
        base.get("authority_rank"),
        transformed.get("authority_rank"),
    )
    if not strict_int(base_authority) or not strict_int(transformed_authority):
        issues.append("invalid_authority_rank")
    elif transformed_authority < base_authority:
        issues.append("evidence_authority_degraded")

    base_gold, transformed_gold = base.get("gold_retrievable"), transformed.get("gold_retrievable")
    if not isinstance(base_gold, bool) or not isinstance(transformed_gold, bool):
        issues.append("invalid_gold_retrievable")
    elif base_gold and not transformed_gold:
        issues.append("gold_evidence_lost")

    if transformed.get("citations_source_bound") is not True:
        issues.append("citation_source_binding_failed")

    expanded = transformed.get("planner_permission_expanded")
    if not isinstance(expanded, bool):
        issues.append("invalid_planner_permission")
        expanded = False
    if expanded:
        issues.append("planner_permission_expanded")
    if (
        str(base.get("answer_status")) in ABSTAIN_OR_REVIEW
        and str(transformed.get("answer_status")) == "answered"
        and expanded
    ):
        issues.append("permissive_rephrase_changed_decision")
    return issues
