from __future__ import annotations

import hashlib
import json
import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

import pytest

import korpus.application.plasticity as plasticity
from korpus.application.determinism import failures, junit_contract, run_json
from korpus.application.plasticity import (
    AdaptationPolicy,
    AdaptationState,
    ObservationWindow,
    RuntimeKnobs,
    propose_adaptation,
    validate_proposal,
)

BASE = RuntimeKnobs(256, 1200, 0.55, 0.60, 0.65)
POLICY = AdaptationPolicy()


def _window() -> ObservationWindow:
    return ObservationWindow(10, 500, 500.0, 0.001, 0.0, 0.001, 0.95)


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"min_candidate_budget": 0}, "candidate-budget"),
        ({"candidate_step": 0}, "candidate_step"),
        ({"min_timeout_ms": 0}, "timeout bounds"),
        ({"timeout_step_ms": 0}, "timeout_step_ms"),
        ({"safety_step": 0.0}, "safety_step"),
        ({"max_safety_threshold": 0.0}, "max_safety_threshold"),
        ({"min_samples": 0}, "sample/cooldown"),
        ({"cooldown_windows": -1}, "sample/cooldown"),
        ({"high_error_rate": 1.1}, "rate policy"),
        ({"healthy_error_rate": 0.03, "high_error_rate": 0.02}, "healthy_error_rate"),
        ({"healthy_overload_rate": 0.03, "high_overload_rate": 0.02}, "healthy_overload_rate"),
        ({"healthy_latency_ms": 1000.0, "high_latency_ms": 900.0}, "healthy latency"),
        ({"healthy_windows_for_recall_expansion": 0}, "healthy window"),
    ],
)
def test_policy_refuses_every_invalid_boundary(updates: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        AdaptationPolicy(**updates)


def test_window_and_state_counter_boundaries_are_fail_closed() -> None:
    with pytest.raises(ValueError, match="sequence/sample"):
        ObservationWindow(-1, 1, 0.0, 0.0, 0.0, 0.0, 1.0)
    with pytest.raises(ValueError, match="state counters"):
        AdaptationState(BASE, last_change_sequence=-2)
    with pytest.raises(ValueError, match="state counters"):
        AdaptationState(BASE, consecutive_healthy_windows=-1)


def test_proposal_exposes_exact_window_sequence() -> None:
    proposal = propose_adaptation(AdaptationState(BASE), _window())
    assert proposal.window_sequence == 10


def _resigned(proposal, proposed: RuntimeKnobs):
    next_state = replace(proposal.next_state, knobs=proposed)
    digest = hashlib.sha256(
        plasticity._canonical_payload(
            proposal.action,
            proposal.input_state,
            proposal.observation,
            POLICY,
            proposed,
            next_state,
            proposal.reasons,
        )
    ).hexdigest()
    return replace(proposal, proposed=proposed, next_state=next_state, proposal_sha256=digest)


@pytest.mark.parametrize(
    ("proposed", "message"),
    [
        (replace(BASE, candidate_budget=1025), "candidate budget"),
        (replace(BASE, retrieval_timeout_ms=5001), "retrieval timeout"),
        (replace(BASE, minimum_score=0.54), "minimum_score"),
        (replace(BASE, minimum_query_coverage=0.59), "minimum_query_coverage"),
        (replace(BASE, minimum_support_score=0.64), "minimum_support_score"),
    ],
)
def test_validator_refuses_even_correctly_rehashed_policy_escapes(
    proposed: RuntimeKnobs, message: str
) -> None:
    proposal = propose_adaptation(AdaptationState(BASE), _window())
    with pytest.raises(ValueError, match=message):
        validate_proposal(_resigned(proposal, proposed))


def _junit(path: Path) -> None:
    suite = ET.Element("testsuite", tests="4", failures="1", errors="1", skipped="1")
    for name, child in (("pass", None), ("fail", "failure"), ("error", "error"), ("skip", "skipped")):
        case = ET.SubElement(suite, "testcase", classname="C", name=name)
        if child:
            ET.SubElement(case, child)
    ET.ElementTree(suite).write(path, encoding="unicode")


def test_determinism_junit_contract_commits_exact_outcomes(tmp_path: Path) -> None:
    path = tmp_path / "junit.xml"
    _junit(path)
    first = junit_contract(path)
    second = junit_contract(path)
    assert first == second
    assert first["tests"] == 4
    assert first["failures"] == first["errors"] == first["skipped"] == 1
    assert len(str(first["outcome_sha256"])) == 64


def test_determinism_json_subprocess_boundary(tmp_path: Path) -> None:
    env = os.environ.copy()
    ok = [sys.executable, "-c", 'import json; print(json.dumps({"status":"PASS"}))']
    rc, payload = run_json(ok, env, tmp_path, 5)
    assert rc == 0 and payload == {"status": "PASS"}
    rc, payload = run_json([sys.executable, "-c", "print('not-json')"], env, tmp_path, 5)
    assert rc == 1 and payload == {}
    rc, payload = run_json([sys.executable, "-c", "raise SystemExit(7)"], env, tmp_path, 5)
    assert rc == 7 and payload == {}


def test_determinism_failure_algebra_is_conjunctive() -> None:
    good = {
        "tests": 4, "skipped": 0, "exit_code": 0, "replay_exit_code": 0,
        "failures": 0, "errors": 0, "outcome_sha256": "a" * 64,
        "semantic_replay_sha256": "b" * 64,
    }
    policy = {"require_identical_test_cardinality": True, "require_zero_failures": True}
    assert failures([good, dict(good)], policy) == []
    bad = dict(good, outcome_sha256="c" * 64, semantic_replay_sha256="d" * 64, exit_code=1)
    found = failures([good, bad], policy)
    assert "at least one deterministic seed run failed" in found
    assert "exact test outcomes differ across hash seeds" in found
    assert "semantic replay digest differs across hash seeds" in found
