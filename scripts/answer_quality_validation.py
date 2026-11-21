"""Strict evidence admission before an answer-quality threshold is compared."""

from __future__ import annotations

import math
from typing import Any

from evaluation_json import is_digest

AXES = ("in_corpus_answered_rate", "out_of_corpus_answered_rate")
MIN_REASON = 20


def finite_rate(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return 0 <= value <= 1 and math.isfinite(value)


def _bucket_problems(bucket: object, stratum: str) -> list[str]:
    if not isinstance(bucket, dict):
        return [f"missing measurement counts for {stratum}"]
    rate, answered, judged = (bucket.get(key) for key in ("rate", "answered", "judged"))
    if not finite_rate(rate):
        return [f"invalid finite [0,1] rate for {stratum}"]
    if type(answered) is not int or type(judged) is not int or not 0 <= answered <= judged:
        return [f"invalid measurement counts for {stratum}"]
    if judged <= 0:
        return [f"no measured denominator for {stratum}"]
    if rate != answered / judged:
        return [f"rate does not match measured counts for {stratum}"]
    return []


def _relaxation_problems(relaxed: object) -> list[str]:
    if not isinstance(relaxed, list):
        return ["relaxation policy must be a list"]
    problems: list[str] = []
    for entry in relaxed:
        if not isinstance(entry, dict) or entry.get("axis") not in AXES:
            problems.append("invalid relaxation axis")
            continue
        reason = entry.get("reason")
        if not isinstance(reason, str) or len(reason.strip()) < MIN_REASON:
            problems.append("a relaxed bound has no recorded reason")
    return problems


def _policy_problems(config: dict[str, Any]) -> list[str]:
    problems = _relaxation_problems(config.get("relaxed", []))
    if config.get("schema") != "korpus.answer-quality-ratchet.v1":
        problems.append("invalid threshold policy schema")
    for section, axis in (("floors", AXES[0]), ("ceilings", AXES[1])):
        policy = config.get(section)
        if not isinstance(policy, dict) or set(policy) != {axis} or not finite_rate(policy[axis]):
            problems.append(f"invalid {section} threshold policy")
    measured = config.get("measured")
    if not isinstance(measured, dict) or not is_digest(measured.get("set_digest")):
        problems.append("invalid complete baseline set digest")
    elif any(not finite_rate(measured.get(axis)) for axis in AXES):
        problems.append("invalid recorded baseline rates")
    return problems


def _cardinality_problems(report: dict[str, Any], config: dict[str, Any]) -> list[str]:
    counts = config.get("case_counts")
    if not isinstance(counts, dict) or set(counts) != {"in_corpus", "out_of_corpus"}:
        return ["invalid frozen set cardinality policy"]
    problems: list[str] = []
    for stratum, expected in counts.items():
        if type(expected) is not int or expected <= 0:
            problems.append(f"invalid frozen case count for {stratum}")
            continue
        bucket = report.get(stratum)
        if not isinstance(bucket, dict) or bucket.get("judged") != expected:
            problems.append(f"measured count differs from frozen set for {stratum}")
    return problems


def validation_problems(report: object, config: object) -> list[str]:
    if not isinstance(report, dict) or not isinstance(config, dict):
        return ["measurement and policy must be JSON objects"]
    problems = _policy_problems(config)
    if report.get("schema") != "korpus.domain-boundary-eval.v1":
        problems.append("invalid measurement schema")
    if report.get("status") != "MEASURED":
        problems.append("report is not a complete measurement")
    if report.get("unreachable") != [] or report.get("invalid", []) != []:
        problems.append("report contains unavailable or invalid measurements")
    if not is_digest(report.get("set_digest")):
        problems.append("invalid complete measured set digest")
    for stratum in ("in_corpus", "out_of_corpus"):
        problems.extend(_bucket_problems(report.get(stratum), stratum))
    problems.extend(_cardinality_problems(report, config))
    return problems
