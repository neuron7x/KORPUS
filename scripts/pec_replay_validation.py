"""Fail-closed validation of counterfactual PEC replay observations."""

from __future__ import annotations

import math

REQUIRED_OBSERVATION_FIELDS = (
    "state_fingerprint",
    "features",
    "authorization_ok",
    "answer_error",
    "quality_ok",
    "answer_status",
    "gold_hit",
    "latency_ms",
    "search_count",
    "planner_calls",
    "semantic_calls",
    "candidate_count",
)
BOOLEAN_FIELDS = ("authorization_ok", "answer_error", "quality_ok", "gold_hit")
NUMERIC_FIELDS = (
    "latency_ms",
    "search_count",
    "planner_calls",
    "semantic_calls",
    "candidate_count",
)
INTEGER_FIELDS = (
    "search_count",
    "planner_calls",
    "semantic_calls",
    "candidate_count",
    "external_tokens",
    "provider_cost_microunits",
)


def _shape_issues(observation: dict[str, object], query_id: str, action: str) -> list[str]:
    issues = [
        f"missing_field:{query_id}:{action}:{field}"
        for field in REQUIRED_OBSERVATION_FIELDS
        if field not in observation
    ]
    fingerprint = observation.get("state_fingerprint")
    if (
        not isinstance(fingerprint, str)
        or len(fingerprint) != 64
        or any(c not in "0123456789abcdef" for c in fingerprint)
    ):
        issues.append(f"invalid_state_fingerprint:{query_id}:{action}")
    if "features" in observation and not isinstance(observation.get("features"), dict):
        issues.append(f"invalid_features:{query_id}:{action}")
    return issues


def _measurement_issues(observation: dict[str, object], query_id: str, action: str) -> list[str]:
    issues: list[str] = []
    for field in BOOLEAN_FIELDS:
        if field in observation and not isinstance(observation.get(field), bool):
            issues.append(f"invalid_boolean:{query_id}:{action}:{field}")
    for field in NUMERIC_FIELDS:
        if field not in observation:
            continue
        value = observation.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            issues.append(f"invalid_measurement:{query_id}:{action}:{field}")
            continue
        try:
            finite = math.isfinite(float(value))
        except (OverflowError, TypeError, ValueError):
            finite = False
        if not finite:
            issues.append(f"invalid_measurement:{query_id}:{action}:{field}")
        elif float(value) < 0.0:
            issues.append(f"negative_measurement:{query_id}:{action}:{field}")
    for field in INTEGER_FIELDS:
        if field not in observation:
            continue
        value = observation.get(field)
        if isinstance(value, bool) or not isinstance(value, int):
            issues.append(f"invalid_integer_measurement:{query_id}:{action}:{field}")
    return issues


def _retrieved_span_issues(observation: dict[str, object], query_id: str, action: str) -> list[str]:
    retrieved = observation.get("retrieved_spans")
    if not isinstance(retrieved, list):
        return [f"missing_retrieved_span_ranks:{query_id}:{action}"]
    issues: list[str] = []
    for index, item in enumerate(retrieved):
        if not isinstance(item, dict) or not str(item.get("span_id", "")):
            issues.append(f"invalid_retrieved_span:{query_id}:{action}:{index}")
            continue
        rank = item.get("rank")
        if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
            issues.append(f"invalid_retrieved_rank:{query_id}:{action}:{index}")
    return issues


def _binding_issues(
    observation: dict[str, object],
    query_id: str,
    action: str,
    expected_corpus_release_id: str | None,
    expected_protocol_sha256: str | None,
    expected_answer_calibration_id: str | None,
) -> list[str]:
    expected = {
        "corpus_release_id": expected_corpus_release_id or "",
        "evaluation_protocol_sha256": expected_protocol_sha256 or "",
        "answer_calibration_id": expected_answer_calibration_id or "",
    }
    issues = [
        f"{field}_binding_mismatch:{query_id}:{action}"
        for field, value in expected.items()
        if str(observation.get(field, "")) != str(value)
    ]
    if not str(observation.get("risk_class", "")):
        issues.append(f"missing_risk_class:{query_id}:{action}")
    if not str(observation.get("judgment", "")):
        issues.append(f"missing_judgment:{query_id}:{action}")
    issues.extend(_retrieved_span_issues(observation, query_id, action))
    quality = observation.get("retrieval_quality")
    if not isinstance(quality, dict):
        issues.append(f"missing_retrieval_quality:{query_id}:{action}")
    else:
        for metric, value in quality.items():
            valid_name = isinstance(metric, str) and bool(metric)
            valid_value = isinstance(value, (int, float)) and not isinstance(value, bool)
            if valid_value:
                try:
                    valid_value = math.isfinite(float(value))
                except (OverflowError, TypeError, ValueError):
                    valid_value = False
            if not valid_name or not valid_value:
                issues.append(f"invalid_retrieval_quality:{query_id}:{action}:{metric}")
    if not isinstance(observation.get("evidence_fingerprints"), list):
        issues.append(f"missing_evidence_fingerprints:{query_id}:{action}")
    return issues


def record_issues(
    observation: dict[str, object],
    *,
    dataset_by_id: dict[str, dict[str, object]],
    actions: tuple[str, ...],
    expected_corpus_release_id: str | None,
    expected_protocol_sha256: str | None,
    expected_answer_calibration_id: str | None,
    require_bindings: bool,
) -> list[str]:
    query_id = str(observation.get("query_id", ""))
    action = str(observation.get("action", ""))
    source = dataset_by_id.get(query_id)
    if source is None:
        return [f"unknown_query_id:{query_id}"]
    issues: list[str] = []
    if str(observation.get("group_id", "")) != str(source.get("group_id", "")):
        issues.append(f"group_binding_mismatch:{query_id}:{action}")
    if action not in actions:
        issues.append(f"unexpected_action:{query_id}:{action}")
    issues.extend(_shape_issues(observation, query_id, action))
    issues.extend(_measurement_issues(observation, query_id, action))
    if require_bindings:
        issues.extend(
            _binding_issues(
                observation,
                query_id,
                action,
                expected_corpus_release_id,
                expected_protocol_sha256,
                expected_answer_calibration_id,
            )
        )
    return issues
