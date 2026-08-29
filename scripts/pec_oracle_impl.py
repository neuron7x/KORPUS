from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.decision_sensitivity import (
    additional_compute_has_decision_value,
    decision_transitions,
)
from korpus.application.numeric_contracts import finite_number, strict_int
from korpus.application.pec_oracle_policy import Outcome
from korpus.application.pec_replay import ReplayOutcome, solve_oracle
from korpus.application.predictive_evidence_control import RetrievalAction
from pec_common import receipt, sha256_file, write_json


def _strict_bool(row: dict[str, object], key: str) -> bool:
    value = row.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"replay observation {key} must be boolean")
    return value


def _strict_int(row: dict[str, object], key: str, default: int | None = None) -> int:
    value = row.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"replay observation {key} must be integer")
    return value


def _strict_nonnegative_number(row: dict[str, object], key: str) -> float:
    # Split, not `not finite_number(value) or value < 0`: a TypeGuard does not narrow the
    # right-hand side of an `or` whose left side is its negation, so the comparison would
    # still be against `object`.
    value = row.get(key)
    if not finite_number(value):
        raise ValueError(f"replay observation {key} must be a finite non-negative number")
    if value < 0.0:
        raise ValueError(f"replay observation {key} must be a finite non-negative number")
    return float(value)


def _strict_rank(item: dict[str, object]) -> int:
    value = item.get("rank")
    if not strict_int(value):
        raise ValueError("replay retrieved span rank must be a positive integer")
    if value < 1:
        raise ValueError("replay retrieved span rank must be a positive integer")
    return value


def _strict_quality(value: object) -> float:
    if not finite_number(value):
        raise ValueError("replay retrieval quality metrics must be finite numbers")
    return float(value)


def _strict_mapping(row: dict[str, object], key: str) -> dict[str, object]:
    """A replay row is JSON: every field is `object` until something refuses the alternative."""
    value = row.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"replay observation {key} must be an object")
    return {str(name): item for name, item in value.items()}


def _strict_sequence(row: dict[str, object], key: str) -> list[object]:
    value = row.get(key, ())
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise ValueError(f"replay observation {key} must be a list")
    return list(value)


def parse(row: dict[str, object]) -> ReplayOutcome:
    return ReplayOutcome(
        query_id=str(row["query_id"]),
        group_id=str(row["group_id"]),
        action=RetrievalAction(str(row["action"])),
        state_fingerprint=str(row["state_fingerprint"]),
        features=_strict_mapping(row, "features"),
        authorization_ok=_strict_bool(row, "authorization_ok"),
        answer_error=_strict_bool(row, "answer_error"),
        quality_ok=_strict_bool(row, "quality_ok"),
        answer_status=str(row["answer_status"]),
        gold_hit=_strict_bool(row, "gold_hit"),
        latency_ms=_strict_nonnegative_number(row, "latency_ms"),
        search_count=_strict_int(row, "search_count"),
        planner_calls=_strict_int(row, "planner_calls"),
        semantic_calls=_strict_int(row, "semantic_calls"),
        candidate_count=_strict_int(row, "candidate_count"),
        external_tokens=_strict_int(row, "external_tokens", 0),
        provider_cost_microunits=_strict_int(row, "provider_cost_microunits", 0),
        decision_reason=str(row.get("decision_reason", "")),
        evidence_fingerprints=tuple(
            str(value) for value in _strict_sequence(row, "evidence_fingerprints")
        ),
        corpus_release_id=str(row.get("corpus_release_id", "")),
        evaluation_protocol_sha256=str(row.get("evaluation_protocol_sha256", "")),
        answer_calibration_id=str(row.get("answer_calibration_id", "")),
        risk_class=str(row.get("risk_class", "")),
        judgment=str(row.get("judgment", "")),
        retrieved_spans=tuple(
            (str(item.get("span_id", "")), _strict_rank(item))
            for item in _strict_sequence(row, "retrieved_spans")
            if isinstance(item, dict)
        ),
        retrieval_quality={
            str(key): _strict_quality(value)
            for key, value in _strict_mapping(row, "retrieval_quality").items()
        },
    )


def decision_record(rows: list[ReplayOutcome]) -> dict[str, object]:
    # ReplayOutcome satisfies the Outcome protocol structurally, but the protocol declares
    # query_id and action as mutable attributes while ReplayOutcome is a frozen dataclass —
    # so the two are not assignment-compatible and list is invariant besides. The cast says
    # what the runtime already relies on; solve_oracle only reads.
    decision = solve_oracle(cast("list[Outcome]", rows))
    transitions = decision_transitions(rows)
    transition_by_action = {row.candidate_action: row for row in transitions}
    chosen = transition_by_action.get(decision.action)
    if chosen is not None and not additional_compute_has_decision_value(chosen):
        decision = decision.__class__(
            query_id=decision.query_id,
            action=RetrievalAction.BASELINE,
            status="UNKNOWN",
            reason="non_baseline_action_without_decision_value",
            admissible_actions=decision.admissible_actions,
        )
    flips = sum(row.decision_changed for row in transitions)
    return {
        "query_id": decision.query_id,
        "group_id": rows[0].group_id,
        "features": dict(rows[0].features),
        "state_fingerprint": rows[0].state_fingerprint,
        "oracle_action": decision.action.value,
        "oracle_status": decision.status,
        "oracle_reason": decision.reason,
        "admissible_actions": list(decision.admissible_actions),
        "decision_transitions": [
            {
                "action": row.candidate_action.value,
                "baseline_decision": row.baseline_decision,
                "candidate_decision": row.candidate_decision,
                "decision_changed": row.decision_changed,
                "candidate_admissible": row.candidate_admissible,
                "safety_recovered": row.safety_recovered,
                "quality_recovered": row.quality_recovered,
                "has_decision_value": additional_compute_has_decision_value(row),
            }
            for row in transitions
        ],
        "decision_flip_count": flips,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--release-gate", action="store_true")
    parser.add_argument("--out", type=Path, default=ROOT / "reports/PEC_ORACLE_CURRENT.json")
    args = parser.parse_args()
    raw = json.loads(args.replay.read_text())
    replay_status = str(raw.get("status", "UNKNOWN"))
    groups: dict[str, list[ReplayOutcome]] = defaultdict(list)
    parse_errors: list[str] = []
    for index, row in enumerate(raw.get("observations", [])):
        try:
            parsed = parse(row)
        except (KeyError, TypeError, ValueError) as exc:
            parse_errors.append(f"observation_{index}:{type(exc).__name__}:{exc}")
            continue
        groups[parsed.query_id].append(parsed)
    decisions = [decision_record(rows) for _, rows in sorted(groups.items())]
    unknown = sum(item["oracle_status"] != "PASS" for item in decisions)
    nonbaseline_without_value = sum(
        item["oracle_reason"] == "non_baseline_action_without_decision_value" for item in decisions
    )
    if replay_status == "FAIL" or parse_errors:
        status = "FAIL"
    elif replay_status != "PASS":
        status = "UNKNOWN"
    else:
        status = (
            "PASS" if decisions and unknown == 0 and nonbaseline_without_value == 0 else "UNKNOWN"
        )
    report = receipt(
        "pec_oracle",
        {
            "status": status,
            "replay_sha256": sha256_file(args.replay),
            "replay_status": replay_status,
            "queries": len(decisions),
            "unknown": unknown,
            "nonbaseline_without_decision_value": nonbaseline_without_value,
            "parse_errors": parse_errors[:100],
            "decisions": decisions,
        },
    )
    write_json(args.out, report)
    print(json.dumps({key: value for key, value in report.items() if key != "decisions"}, indent=2))
    return 0 if status == "PASS" or (status == "UNKNOWN" and not args.release_gate) else 1
