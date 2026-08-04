"""Aggregate independently produced gate artifacts into one release verdict.

Destruction stage 2026-08-03 showed the aggregator calling a run successful when
the JUnit report contained ``tests="0"``: it only asked whether any test had
failed, and no test had, because none had run. The same file declared
``ruff``/``mypy`` "NOT_EXECUTED … REQUIRED_IN_GITLAB" and still emitted PASS —
a verdict about tools that were never invoked.

The predicates below are therefore stated over *evidence of execution* first and
outcome second: a suite with no tests, a suite that skipped almost everything, or
a quality tool with no recorded run cannot reach PASS. Thresholds live in the
operational policy so the aggregator measures rather than decides.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from korpus.application.provenance import verify_reports

PROVENANCE_BOUND_REPORTS = ("eval", "mutation", "migration", "scale")


@dataclass(frozen=True)
class AssuranceResult:
    status: str
    checks: Mapping[str, bool]
    failures: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


def _as_int(value: Any, default: int = -1) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = -1.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def evaluate_assurance(
    policy: Mapping[str, Any],
    junit: Mapping[str, Any],
    coverage: Mapping[str, Any],
    reports: Mapping[str, Mapping[str, Any]],
    quality: Mapping[str, Any] | None,
    source_digest: str | None,
) -> AssuranceResult:
    """Decide whether the assembled evidence supports a release verdict.

    ``junit`` and ``coverage`` are the attribute maps of the corresponding XML
    roots; ``quality`` is the recorded ruff/mypy execution, or None when no run
    was recorded at all — which is a failure, not an absence of opinion.
    """

    settings = policy["assurance"]
    executed_tests = _as_int(junit.get("tests"))
    skipped = _as_int(junit.get("skipped"), 0)
    failures = _as_int(junit.get("failures"))
    errors = _as_int(junit.get("errors"))
    executed_without_skips = executed_tests - max(skipped, 0)
    quality_tools = tuple(settings["required_quality_tools"])
    recorded_tools = quality.get("tools", {}) if isinstance(quality, Mapping) else {}
    tools_passed = isinstance(recorded_tools, Mapping) and all(
        isinstance(recorded_tools.get(tool), Mapping)
        and recorded_tools[tool].get("status") == "PASS"
        and _as_int(recorded_tools[tool].get("exit_code")) == 0
        for tool in quality_tools
    )

    provenance_ok, provenance_reasons = (
        verify_reports(
            {name: reports[name] for name in PROVENANCE_BOUND_REPORTS if name in reports},
            source_digest,
        )
        if source_digest is not None
        else (False, ("source digest was not supplied to the aggregator",))
    )
    missing_reports = tuple(
        name for name in PROVENANCE_BOUND_REPORTS if name not in reports
    )

    checks = {
        # "No test failed" is true of a run with no tests. Execution is a separate
        # predicate from outcome and must be asserted first.
        "tests_executed": executed_tests >= _as_int(settings["minimum_tests"]),
        "tests_not_mostly_skipped": executed_without_skips
        >= _as_int(settings["minimum_executed_tests"]),
        "tests_outcome": failures == 0 and errors == 0,
        "coverage_line": _as_float(coverage.get("line-rate"))
        >= _as_float(settings["minimum_line_rate"]),
        "coverage_branch": _as_float(coverage.get("branch-rate"))
        >= _as_float(settings["minimum_branch_rate"]),
        "quality_tooling_executed": tools_passed,
        "reports_present": not missing_reports,
        "evidence_provenance": provenance_ok,
        "eval": _as_float(reports.get("eval", {}).get("pass_rate")) == 1.0,
        # Over the whole catalogue, not over the mutants that still apply: an
        # unapplied mutant leaves mutation_score's denominator and the score reads
        # 1.000 for a catalogue that shrank (observed 2026-08-03, ADR-0008).
        "mutation": _as_float(reports.get("mutation", {}).get("mutation_score_over_catalogue"))
        == 1.0,
        "migration": reports.get("migration", {}).get("table_set_match") is True,
        "scale": reports.get("scale", {}).get("status") == "PASS",
        "operational": reports.get("operational", {}).get("status") == "PASS",
    }
    reasons = tuple(name for name, ok in checks.items() if not ok) + provenance_reasons
    if missing_reports:
        reasons += (f"missing reports: {', '.join(missing_reports)}",)
    return AssuranceResult(
        status="PASS" if not reasons else "FAIL",
        checks=checks,
        failures=reasons,
    )
