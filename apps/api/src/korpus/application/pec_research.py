"""Executable PEC research hypotheses with fail-closed scientific semantics.

These functions measure evidence; they never grant runtime authority.  A missing,
underpowered, synthetic, or unbound observation is reported as UNKNOWN by the caller.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping

from korpus.application.evidence_state import FEATURE_NAMES
from korpus.application.numeric_contracts import (
    bounded_number,
    finite_number,
    nonnegative_count,
    require_count,
    require_rate,
)
from korpus.application.pec_replay import replay_priority
from korpus.application.pec_training import TrainingRow, nested_group_validation
from korpus.application.statistical_bounds import hoeffding_upper_bound


def simultaneous_hoeffding_upper(errors: int, samples: int, delta: float, hypotheses: int) -> float:
    """One-sided simultaneous bound via Hoeffding + union bound across strata."""
    return hoeffding_upper_bound(errors, samples, delta, hypotheses=hypotheses)


def conditional_risk_report(
    rows: Iterable[Mapping[str, object]],
    *,
    stratum_key: str,
    error_key: str,
    risk_limit: float,
    delta: float,
    minimum_samples: int,
) -> dict[str, object]:
    risk_limit = require_rate(risk_limit, label="risk_limit")
    delta = require_rate(delta, label="delta")
    if not 0.0 < delta < 1.0:
        raise ValueError("delta must be strictly inside (0, 1)")
    minimum_samples = require_count(minimum_samples, positive=True, label="minimum_samples")
    grouped: dict[str, list[bool]] = defaultdict(list)
    invalid = 0
    for row in rows:
        stratum = str(row.get(stratum_key, "")).strip()
        error = row.get(error_key)
        if not stratum or not isinstance(error, bool):
            invalid += 1
            continue
        grouped[stratum].append(error)
    count = max(len(grouped), 1)
    strata: dict[str, object] = {}
    admitted = 0
    for name, values in sorted(grouped.items()):
        errors = sum(values)
        upper = simultaneous_hoeffding_upper(errors, len(values), delta, count)
        is_admitted = len(values) >= minimum_samples and upper <= risk_limit
        admitted += int(is_admitted)
        strata[name] = {
            "samples": len(values),
            "errors": errors,
            "upper_error_bound": upper,
            "risk_limit": risk_limit,
            "admitted": is_admitted,
            "fallback_required": not is_admitted,
        }
    status = "FAIL" if invalid else ("PASS" if grouped else "UNKNOWN")
    return {
        "status": status,
        "simultaneous_delta": delta,
        "strata": strata,
        "strata_total": len(grouped),
        "strata_admitted": admitted,
        "invalid_rows": invalid,
    }


def feature_ablation_generalization(rows: Iterable[TrainingRow]) -> dict[str, object]:
    data = list(rows)
    if not data:
        return {"status": "UNKNOWN", "reason": "no_training_rows"}
    full = nested_group_validation(data)
    if full["status"] != "PASS":
        return {"status": "UNKNOWN", "reason": "nested_full_model_not_estimable", "full": full}
    full_accuracy = bounded_number(full.get("oof_accuracy"), 0.0, 1.0)
    if full_accuracy is None:
        return {"status": "UNKNOWN", "reason": "invalid_full_model_accuracy", "full": full}
    ablations: dict[str, object] = {}
    for feature in FEATURE_NAMES:
        masked = [
            TrainingRow(
                row.query_id,
                row.group_id,
                {k: v for k, v in row.features.items() if k != feature},
                row.label,
            )
            for row in data
        ]
        result = nested_group_validation(masked)
        accuracy = result.get("oof_accuracy")
        ablations[feature] = {
            "status": result["status"],
            "oof_accuracy": accuracy,
            "delta_vs_full": (
                None
                if (parsed_accuracy := bounded_number(accuracy, 0.0, 1.0)) is None
                else parsed_accuracy - full_accuracy
            ),
        }
    return {"status": "PASS", "full": full, "ablations": ablations}


def _optional_bool(row: Mapping[str, object], key: str) -> bool:
    value = row.get(key, False)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be boolean")
    return value


def _optional_count(row: Mapping[str, object], key: str) -> int:
    value = row.get(key, 0)
    parsed = nonnegative_count(value)
    if parsed is None:
        raise ValueError(f"{key} must be a non-negative integer")
    return parsed


def _failure(row: Mapping[str, object]) -> bool:
    return any(
        _optional_bool(row, key)
        for key in (
            "authorization_violation",
            "accepted_answer_error",
            "false_abstention",
            "controller_oracle_disagreement",
            "out_of_support",
        )
    )


def _hypergeom_tail(population: int, successes: int, draws: int, observed: int) -> float:
    if population <= 0 or successes < 0 or draws < 0:
        return 1.0
    denominator = math.comb(population, draws)
    if denominator == 0:
        return 1.0
    maximum = min(successes, draws)
    minimum = max(observed, 0)
    total = sum(
        math.comb(successes, hits) * math.comb(population - successes, draws - hits)
        for hits in range(minimum, maximum + 1)
        if 0 <= draws - hits <= population - successes
    )
    return min(1.0, total / denominator)


def replay_priority_enrichment(
    rows: Iterable[Mapping[str, object]],
    *,
    top_fraction: float = 0.2,
    alpha: float = 0.05,
) -> dict[str, object]:
    if not finite_number(top_fraction) or not 0.0 < float(top_fraction) <= 1.0:
        return {"status": "UNKNOWN", "reason": "insufficient_rows_or_fraction"}
    alpha = require_rate(alpha, label="alpha")
    if not 0.0 < alpha <= 1.0:
        raise ValueError("alpha must be inside (0, 1]")
    top_fraction = float(top_fraction)
    data = list(rows)
    if not data:
        return {"status": "UNKNOWN", "reason": "insufficient_rows_or_fraction"}
    ranked = sorted(data, key=replay_priority)
    draws = max(1, math.ceil(len(data) * top_fraction))
    failures = sum(_failure(row) for row in data)
    captured = sum(_failure(row) for row in ranked[:draws])
    p_value = _hypergeom_tail(len(data), failures, draws, captured)
    expected = failures * draws / len(data)
    status = "PASS" if failures and captured > expected and p_value <= alpha else "UNKNOWN"
    return {
        "status": status,
        "rows": len(data),
        "failures": failures,
        "top_rows": draws,
        "failures_captured": captured,
        "uniform_expected": expected,
        "hypergeometric_tail_p": p_value,
        "alpha": alpha,
    }


def observed_information_gain(rows: Iterable[Mapping[str, object]]) -> dict[str, object]:
    """Compare every action to STOP as a vector; no weighted utility is introduced."""
    grouped: dict[str, dict[str, Mapping[str, object]]] = defaultdict(dict)
    for row in rows:
        grouped[str(row.get("query_id", ""))][str(row.get("action", ""))] = row
    comparisons: list[dict[str, object]] = []
    for query_id, actions in sorted(grouped.items()):
        baseline = actions.get("STOP_USE_CURRENT_EVIDENCE")
        if not query_id or baseline is None:
            continue
        raw_base_quality = baseline.get("retrieval_quality")
        base_quality: Mapping[str, object] = (
            raw_base_quality if isinstance(raw_base_quality, Mapping) else {}
        )
        for action, row in sorted(actions.items()):
            if action == "STOP_USE_CURRENT_EVIDENCE":
                continue
            raw_quality = row.get("retrieval_quality")
            quality: Mapping[str, object] = raw_quality if isinstance(raw_quality, Mapping) else {}
            metrics = sorted(set(base_quality) & set(quality))
            deltas: dict[str, float] = {}
            for key in metrics:
                candidate_value, baseline_value = quality[key], base_quality[key]
                if not finite_number(candidate_value) or not finite_number(baseline_value):
                    raise ValueError(f"retrieval_quality[{key}] must contain finite numbers")
                deltas[key] = float(candidate_value) - float(baseline_value)
            comparisons.append(
                {
                    "query_id": query_id,
                    "action": action,
                    "gold_hit_delta": int(_optional_bool(row, "gold_hit"))
                    - int(_optional_bool(baseline, "gold_hit")),
                    "quality_ok_delta": int(_optional_bool(row, "quality_ok"))
                    - int(_optional_bool(baseline, "quality_ok")),
                    "retrieval_quality_deltas": deltas,
                    "extra_searches": _optional_count(row, "search_count")
                    - _optional_count(baseline, "search_count"),
                    "extra_planner_calls": _optional_count(row, "planner_calls")
                    - _optional_count(baseline, "planner_calls"),
                    "extra_semantic_calls": _optional_count(row, "semantic_calls")
                    - _optional_count(baseline, "semantic_calls"),
                }
            )
    return {"status": "PASS" if comparisons else "UNKNOWN", "comparisons": comparisons}


def production_judgment_validity(rows: Iterable[Mapping[str, object]]) -> dict[str, object]:
    data = list(rows)
    invalid: list[str] = []
    judged = 0
    for row in data:
        rid = str(row.get("id", ""))
        production_judged = row.get("production_judged")
        if not isinstance(production_judged, bool):
            invalid.append(f"invalid_production_judged:{rid}")
            continue
        if not production_judged:
            continue
        judged += 1
        digest = str(row.get("judgment_provenance_sha256", ""))
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            invalid.append(f"invalid_judgment_provenance:{rid}")
        if not str(row.get("adjudication_protocol", "")).strip():
            invalid.append(f"missing_adjudication_protocol:{rid}")
    status = "FAIL" if invalid else ("PASS" if judged == len(data) and data else "UNKNOWN")
    return {
        "status": status,
        "rows": len(data),
        "production_judged_rows": judged,
        "invalid": invalid[:100],
    }


def research_status(
    validity: Mapping[str, object], components: Iterable[Mapping[str, object]]
) -> tuple[str, bool]:
    """Grant scientific authority only when production judgment validity itself passes."""
    statuses = [
        str(validity.get("status", "UNKNOWN")),
        *(str(item.get("status", "UNKNOWN")) for item in components),
    ]
    authority = validity.get("status") == "PASS"
    if "FAIL" in statuses:
        return "FAIL", authority
    if authority and all(status == "PASS" for status in statuses):
        return "PASS", True
    return "UNKNOWN", authority
