"""Mechanical reference judgments; unavailable proof never becomes success."""

from __future__ import annotations

from typing import Any

from reference_eval_citations import SpanReader, citation_problems
from reference_eval_metrics import ABSTAINED


def _authority_problems(case: dict[str, Any], answer: dict[str, Any]) -> list[str]:
    if not case.get("must_not_claim_binding") or answer.get("status") != "answered":
        return []
    limitations = answer.get("limitations")
    if not isinstance(limitations, list) or not any(
        isinstance(item, str) and item.strip() for item in limitations
    ):
        return ["an analytical corpus answered with no limitations stated"]
    return []


def _case_problems(
    case: dict[str, Any], answer: dict[str, Any], cited_versions: list[str]
) -> list[str]:
    status = answer.get("status")
    problems: list[str] = []
    if not isinstance(status, str) or status not in {"answered", *ABSTAINED}:
        return ["unexpected answer status"]
    if (
        case["kind"] == "retrieval"
        and status == "answered"
        and not set(cited_versions).intersection(case["must_cite_one_of_if_answered"])
    ):
        problems.append("answered without citing a version holding the target evidence")
    if case["expect"] in {"abstained", "blocked_or_abstained"} and status not in ABSTAINED:
        problems.append("expected an abstention")
    if case["kind"] == "refusal" and answer.get("citations"):
        problems.append("cited a source for terms that are not in the corpus")
    problems.extend(_authority_problems(case, answer))
    return problems


def judge(
    case: dict[str, Any], answer: dict[str, Any], span_reader: SpanReader | None = None
) -> dict[str, Any]:
    citations = answer.get("citations", [])
    reasons, missing = citation_problems(citations, span_reader)
    objects = (
        [item for item in citations if isinstance(item, dict)]
        if isinstance(citations, list)
        else []
    )
    cited_versions = sorted(
        {item["version_id"] for item in objects if isinstance(item.get("version_id"), str)}
    )
    reasons.extend(_case_problems(case, answer, cited_versions))
    if answer.get("status") == "answered" and not objects:
        reasons.append("answered without citations")
    # An independently observed failure outranks a second unavailable source.
    unavailable = bool(missing) and not reasons
    verdict: dict[str, Any] = {
        "id": case["id"],
        "kind": case["kind"],
        "stratum": case["stratum"],
        "status": answer.get("status"),
        "decision_reason": answer.get("decision_reason"),
        "citations": len(objects),
        "passed": False if reasons else (None if unavailable else True),
        "unavailable": unavailable,
        "reasons": [*reasons, *missing],
    }
    if case["kind"] == "retrieval":
        verdict["cited_versions"] = cited_versions
        verdict["expected_versions"] = sorted(case["must_cite_one_of_if_answered"])
    return verdict
