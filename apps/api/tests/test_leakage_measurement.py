"""The leakage metric must have a denominator, and the gate must read it.

Destruction stage, 2026-08-03: `leakage_failures` could only become non-zero for
dataset rows carrying a `forbidden` key, and 2 of the 30 rows carried one. Injecting a
real `training → PUBLIC` disclosure produced `30/30`, `leakage_failures=0`,
`access_noninterference=true` and 193 green tests — the metric measured nothing and
reported success.

Two properties are stated. The evaluation reports how many rows it was *able* to
measure, and the operational gate fails when that number is too small to be evidence —
so a run in which nothing could leak can no longer be mistaken for a run in which
nothing did.
"""

from __future__ import annotations

from typing import Any

from apps.api.tests.test_operations import evaluate, passing_reports


def _verdict(**overrides: Any) -> Any:
    reports = passing_reports()
    reports["eval"].update(overrides)
    return evaluate(reports)


def test_the_gate_passes_when_leakage_was_measured_and_none_occurred() -> None:
    verdict = _verdict(leakage_checks=26)

    assert verdict.checks["access_noninterference"] is True
    assert verdict.checks["access_noninterference_measured"] is True
    assert verdict.status == "PASS", verdict.failures


def test_the_gate_fails_when_the_metric_had_nothing_to_measure() -> None:
    """Zero failures over zero measurable rows is the metric reporting it never ran."""
    verdict = _verdict(leakage_checks=0)

    assert verdict.checks["access_noninterference_measured"] is False
    assert verdict.status != "PASS"


def test_the_gate_fails_on_the_historical_denominator() -> None:
    """2 of 30 rows was the state in which a real disclosure went unnoticed."""
    verdict = _verdict(leakage_checks=2)

    assert verdict.checks["access_noninterference_measured"] is False
    assert verdict.status != "PASS"


def test_a_report_without_the_field_at_all_fails_the_gate() -> None:
    """An eval report predating the measurement must not read as a measured one."""
    reports = passing_reports()
    reports["eval"].pop("leakage_checks", None)

    verdict = evaluate(reports)

    assert verdict.checks["access_noninterference_measured"] is False
    assert verdict.status != "PASS"
