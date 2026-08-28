from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
# `run_reference_eval` imports its sibling by bare name, so `scripts/` has to be on the
# path before it is executed. Other modules happen to put it there, which made this file
# pass in a full run and fail in isolation: the regression shards found it as a
# collection error in shard 028, where none of those modules are collected first.
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "run_reference_eval", ROOT / "scripts/run_reference_eval.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
METRICS = MODULE.retrieval_effectiveness.__globals__


def _result(status: str, passed: bool = True) -> dict[str, object]:
    return {"kind": "retrieval", "status": status, "passed": passed}


def test_retrieval_safety_pass_cannot_hide_zero_answer_yield() -> None:
    metrics = MODULE.retrieval_effectiveness(
        [_result("insufficient_evidence"), _result("requires_human_review")]
    )

    assert metrics["cases"] == 2
    assert metrics["abstained"] == 2
    assert metrics["answer_yield"] == 0.0
    assert metrics["supported_answer_rate"] == 0.0


def test_supported_answer_rate_excludes_wrong_source_answers() -> None:
    metrics = MODULE.retrieval_effectiveness(
        [_result("answered"), _result("answered", False), _result("insufficient_evidence")]
    )

    assert metrics["answered"] == 2
    assert metrics["answered_wrong_or_invalid_source"] == 1
    assert metrics["supported_answers"] == 1
    assert metrics["supported_answer_rate"] == pytest.approx(1 / 3)


def test_wilson_interval_is_bounded_and_not_false_certainty() -> None:
    lower, upper = METRICS["wilson_interval"](135, 135)

    assert 0.97 < lower < 1.0
    assert upper == 1.0
    assert METRICS["wilson_interval"](0, 0) == [0.0, 0.0]
