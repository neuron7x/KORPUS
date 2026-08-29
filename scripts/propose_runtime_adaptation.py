#!/usr/bin/env python3
"""Produce a deterministic, auditable runtime adaptation proposal from JSON inputs."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT)]

from korpus.application.numeric_contracts import (  # noqa: E402
    require_positive_number,
    require_rate,
)
from korpus.application.plasticity import (  # noqa: E402
    AdaptationState,
    ObservationWindow,
    RuntimeKnobs,
    propose_adaptation,
    validate_proposal,
)
from korpus.application.plasticity_config import load_plasticity_policy  # noqa: E402


def _int_field(payload: dict[str, object], key: str, default: int) -> int:
    """A JSON field is `object`; int() of one is a type error, not a conversion."""
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"state.{key} must be an integer")
    return value


def _observation_window(payload: dict[str, object]) -> ObservationWindow:
    """Build the window field by field so each one is refused at its own name.

    `ObservationWindow(**payload)` type-checks as one opaque spread: mypy cannot see which
    key is wrong, and at runtime a wrong type surfaces as a TypeError naming the dataclass
    rather than the field the operator has to fix.
    """
    return ObservationWindow(
        sequence=_int_field(payload, "sequence", 0),
        samples=_int_field(payload, "samples", 0),
        p95_latency_ms=require_positive_number(
            payload.get("p95_latency_ms"), label="window.p95_latency_ms"
        ),
        error_rate=require_rate(payload.get("error_rate"), label="window.error_rate"),
        contradiction_rate=require_rate(
            payload.get("contradiction_rate"), label="window.contradiction_rate"
        ),
        overload_rate=require_rate(payload.get("overload_rate"), label="window.overload_rate"),
        recall_at_20=require_rate(payload.get("recall_at_20"), label="window.recall_at_20"),
    )


def _object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON input must be an object: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--window", type=Path, required=True)
    parser.add_argument(
        "--policy", type=Path, default=ROOT / "config/operations/plasticity-policy.json"
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        state_raw = _object(args.state)
        knobs_raw = state_raw.get("knobs")
        if not isinstance(knobs_raw, dict):
            raise ValueError("state.knobs must be an object")
        state = AdaptationState(
            knobs=RuntimeKnobs(**knobs_raw),
            last_change_sequence=_int_field(state_raw, "last_change_sequence", -1),
            consecutive_healthy_windows=_int_field(state_raw, "consecutive_healthy_windows", 0),
        )
        window = _observation_window(_object(args.window))
        policy, _policy_sha256 = load_plasticity_policy(args.policy)
        proposal = propose_adaptation(state, window, policy)
        validate_proposal(proposal, policy)
    except (TypeError, ValueError) as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}, ensure_ascii=False))
        return 2

    payload = {
        "schema": "korpus.adaptation-proposal.v2",
        "status": "PROPOSED" if proposal.changed else "NOOP",
        "action": proposal.action.value,
        "input_state": asdict(proposal.input_state),
        "observation": asdict(proposal.observation),
        "proposed": asdict(proposal.proposed),
        "next_state": asdict(proposal.next_state),
        "reasons": list(proposal.reasons),
        "policy_sha256": proposal.policy_sha256,
        "proposal_sha256": proposal.proposal_sha256,
        "promotion": "GOVERNED_REVIEW_REQUIRED" if proposal.changed else "NOT_REQUIRED",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
