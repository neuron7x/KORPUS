#!/usr/bin/env python3
"""Bounded exhaustive checker for KORPUS assurance and release invariants.

This is deliberately executable rather than a prose/TLA-only claim. It enumerates the
small finite state spaces that matter to the release policy and exits non-zero on a
counterexample. TLA+ specifications remain the human/formal model; this checker is the
CI-portable destruction proof that runs with the product's Python toolchain.
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.assurance_calculus import (  # noqa: E402
    DimensionPolicy,
    EvidenceClass,
    EvidencePoint,
    GateRequirement,
    ReadinessPolicy,
    dominates,
    evaluate_gate,
    join_evidence,
    weighted_score_is_bounded,
)
from korpus.application.provenance import compute_source_digest  # noqa: E402
from korpus.application.release_state_machine import (  # noqa: E402
    PromotionPolicy,
    ReleaseIdentity,
    ReleaseRecord,
    ReleaseStage,
    evaluate_promotion,
)

MODEL_SOURCE = "a" * 64
OTHER_SOURCE = "b" * 64
MODEL_RELEASE = "v-model"


def current_release() -> str:
    path = ROOT / "apps/api/src/korpus/release.json"
    return str(json.loads(path.read_text(encoding="utf-8"))["tag"])


def point(cls: EvidenceClass, status: str) -> EvidencePoint:
    executed = cls >= EvidenceClass.EXECUTED
    negative = cls >= EvidenceClass.EXECUTED_WITH_NEGATIVE_CONTROL
    independent = cls >= EvidenceClass.INDEPENDENT_ATTESTED
    return EvidencePoint(
        cls,
        MODEL_SOURCE,
        MODEL_RELEASE,
        status,
        executed=executed,
        negative_control=negative,
        independent=independent,
        attested=independent,
    )


def check_join_laws(failures: list[str], counts: dict[str, int]) -> None:
    values = [point(cls, status) for cls in EvidenceClass for status in ("UNKNOWN", "PASS", "FAIL")]
    for left, right in itertools.product(values, repeat=2):
        counts["join_pairs"] += 1
        if join_evidence(left, right) != join_evidence(right, left):
            failures.append("evidence_join.not_commutative")
            return
        if join_evidence(left, left) != left:
            failures.append("evidence_join.not_idempotent")
            return
        # UNKNOWN is an information bottom for outcome; it must not turn a known PASS
        # into FAIL merely by being observed.
        if (
            left.status == "PASS"
            and right.status == "UNKNOWN"
            and join_evidence(left, right).status != "PASS"
        ):
            failures.append("evidence_join.unknown_corrupts_pass")
            return
    for a, b, c in itertools.product(values, repeat=3):
        counts["join_triples"] += 1
        if join_evidence(join_evidence(a, b), c) != join_evidence(a, join_evidence(b, c)):
            failures.append("evidence_join.not_associative")
            return


def check_dominance(failures: list[str], counts: dict[str, int]) -> None:
    for cls in EvidenceClass:
        passed = point(cls, "PASS")
        failed = point(cls, "FAIL")
        unknown = point(cls, "UNKNOWN")
        counts["dominance_cases"] += 3
        if dominates(passed, failed) or dominates(failed, passed):
            failures.append("evidence_dominance.contradictory_outcomes_ordered")
            return
        if not dominates(passed, unknown) or not dominates(failed, unknown):
            failures.append("evidence_dominance.unknown_not_bottom")
            return


def check_gate_fail_closed(failures: list[str], counts: dict[str, int]) -> None:
    requirement = GateRequirement(
        "production",
        EvidenceClass.EXECUTED_WITH_NEGATIVE_CONTROL,
        require_negative_control=True,
    )
    candidates = [
        None,
        point(EvidenceClass.NONE, "PASS"),
        point(EvidenceClass.EXECUTED, "PASS"),
        point(EvidenceClass.EXECUTED_WITH_NEGATIVE_CONTROL, "FAIL"),
        EvidencePoint(
            EvidenceClass.EXECUTED_WITH_NEGATIVE_CONTROL,
            OTHER_SOURCE,
            MODEL_RELEASE,
            "PASS",
            executed=True,
            negative_control=True,
        ),
        EvidencePoint(
            EvidenceClass.EXECUTED_WITH_NEGATIVE_CONTROL,
            MODEL_SOURCE,
            "v9.9.9",
            "PASS",
            executed=True,
            negative_control=True,
        ),
    ]
    for candidate in candidates:
        counts["gate_negative_cases"] += 1
        passed, _ = evaluate_gate(
            requirement,
            candidate,
            source_digest=MODEL_SOURCE,
            release=MODEL_RELEASE,
        )
        if passed:
            failures.append("gate_fail_closed.false_accept")
            return
    good = point(EvidenceClass.EXECUTED_WITH_NEGATIVE_CONTROL, "PASS")
    passed, reasons = evaluate_gate(
        requirement, good, source_digest=MODEL_SOURCE, release=MODEL_RELEASE
    )
    counts["gate_positive_cases"] += 1
    if not passed or reasons:
        failures.append("gate_fail_closed.false_reject")


def check_weight_bounds(failures: list[str], counts: dict[str, int]) -> None:
    dimensions = tuple(DimensionPolicy(f"d{i}", 0.125) for i in range(8))
    policy = ReadinessPolicy(dimensions, ())
    for scores in itertools.product((0.0, 50.0, 100.0), repeat=8):
        counts["weighted_vectors"] += 1
        if not weighted_score_is_bounded(policy, scores):
            failures.append(f"weighted_score.out_of_bounds:{scores!r}")
            return


def check_release_machine(failures: list[str], counts: dict[str, int]) -> None:
    unit = GateRequirement("unit", EvidenceClass.EXECUTED)
    mutation = GateRequirement("mutation", EvidenceClass.EXECUTED_WITH_NEGATIVE_CONTROL, True)
    external = GateRequirement(
        "external",
        EvidenceClass.INDEPENDENT_ATTESTED,
        True,
        True,
        True,
    )
    policy = PromotionPolicy((unit,), (unit, mutation), (unit, mutation, external))
    gates = {
        "unit": point(EvidenceClass.EXECUTED, "PASS"),
        "mutation": point(EvidenceClass.EXECUTED_WITH_NEGATIVE_CONTROL, "PASS"),
        "external": point(EvidenceClass.INDEPENDENT_ATTESTED, "PASS"),
    }
    identity = ReleaseIdentity(MODEL_RELEASE, MODEL_SOURCE, "e" * 64)
    allowed_next = {
        ReleaseStage.DRAFT: ReleaseStage.INTEGRATED,
        ReleaseStage.INTEGRATED: ReleaseStage.VERIFIED,
        ReleaseStage.VERIFIED: ReleaseStage.RELEASE_CANDIDATE,
        ReleaseStage.RELEASE_CANDIDATE: ReleaseStage.PRODUCTION_AUTHORIZED,
    }
    for current, target in itertools.product(ReleaseStage, repeat=2):
        record = ReleaseRecord(
            identity,
            current,
            "author",
            withdrawal_reason="done" if current == ReleaseStage.WITHDRAWN else None,
        )
        verdict = evaluate_promotion(
            record,
            target,
            policy,
            gates,
            verifier_subject="independent-verifier",
        )
        counts["release_transitions"] += 1
        expected = allowed_next.get(current) == target
        if target == ReleaseStage.WITHDRAWN:
            expected = False  # withdrawal is only valid through withdraw(reason)
        if verdict.allowed != expected:
            failures.append(
                f"release_machine.transition:{current.name}->{target.name}:expected={expected}:actual={verdict.allowed}"
            )
            return

    candidate = ReleaseRecord(identity, ReleaseStage.RELEASE_CANDIDATE, "author")
    self_verified = evaluate_promotion(
        candidate,
        ReleaseStage.PRODUCTION_AUTHORIZED,
        policy,
        gates,
        verifier_subject="author",
    )
    counts["release_independence_cases"] += 1
    if self_verified.allowed:
        failures.append("release_machine.self_authorization")


def main() -> int:
    failures: list[str] = []
    counts = {
        "join_pairs": 0,
        "join_triples": 0,
        "dominance_cases": 0,
        "gate_negative_cases": 0,
        "gate_positive_cases": 0,
        "weighted_vectors": 0,
        "release_transitions": 0,
        "release_independence_cases": 0,
    }
    check_join_laws(failures, counts)
    check_dominance(failures, counts)
    check_gate_fail_closed(failures, counts)
    check_weight_bounds(failures, counts)
    check_release_machine(failures, counts)
    payload = {
        "schema": "korpus.assurance-model-check.v2",
        "status": "PASS" if not failures else "FAIL",
        "release": current_release(),
        "source_tree_sha256": compute_source_digest(ROOT),
        "model_identity": {"source": MODEL_SOURCE, "release": MODEL_RELEASE},
        "counts": counts,
        "total_states_checked": sum(counts.values()),
        "failures": failures,
        "properties": [
            "evidence join commutative/idempotent/associative",
            "PASS and FAIL are incomparable under dominance",
            "UNKNOWN is outcome bottom",
            "mandatory gate mismatches fail closed",
            "weighted readiness remains in [0,100]",
            "release promotion is sequential and withdrawal uses a reason-bearing API",
            "production verifier cannot equal author",
        ],
    }
    print(json.dumps(payload, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
