"""Every gate predicate must be shown to be capable of failing.

§2.8 of `ADMISSION_BOUNDARY_2026-08-03.md` is the standing ground: four gates were
demonstrated to be incapable of failing, and closing those four says nothing about the
fifth. "Доки ці гейти не здатні почервоніти, їхнє «PASS» не є свідченням про систему."

So the requirement is stated once, over all of them: for every predicate the release
gates report, there is a case here that makes exactly that predicate false, and the
inventory of predicates is read from the code rather than kept by hand. A predicate
added tomorrow fails `test_every_gate_predicate_has_a_negative_control` until someone
writes the case that breaks it.

The dual test matters as much: the passing artifacts must actually pass. A negative
control over inputs that fail for some other reason proves nothing.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from korpus.application.assurance import evaluate_assurance
from korpus.application.gate_inventory import assurance_predicates, operational_predicates
from korpus.application.provenance import PROVENANCE_KEY

from apps.api.tests.test_operations import TREE_DIGEST, evaluate, passing_reports


def _stamped(reports: dict[str, Any]) -> dict[str, Any]:
    for report in reports.values():
        report.setdefault(
            PROVENANCE_KEY,
            {
                "schema_version": 1,
                "source_digest": TREE_DIGEST,
                "generator": "test",
                "generated_at": "2026-08-05T00:00:00+00:00",
            },
        )
    return reports


def _drop_eval(reports: dict[str, Any]) -> dict[str, Any]:
    reports.pop("eval")
    return reports


#: predicate -> how to break exactly it, leaving the rest of the evidence sound.
OPERATIONAL_BREAKERS: dict[str, Any] = {
    "reports_present": _drop_eval,
    # A foreign digest rather than a missing block: `evaluate` stamps reports that
    # carry none, so removing it would test the helper instead of the gate.
    "evidence_provenance": lambda reports: {
        name: report | {PROVENANCE_KEY: report[PROVENANCE_KEY] | {"source_digest": "d" * 64}}
        for name, report in reports.items()
    },
    "eval_pass_rate": lambda reports: reports | {"eval": reports["eval"] | {"pass_rate": 0.5}},
    "citation_integrity": lambda reports: (
        reports | {"eval": reports["eval"] | {"citation_failures": 1}}
    ),
    "access_noninterference": lambda reports: (
        reports | {"eval": reports["eval"] | {"leakage_failures": 1}}
    ),
    "access_noninterference_measured": lambda reports: (
        reports | {"eval": reports["eval"] | {"leakage_checks": 0}}
    ),
    "determinism": lambda reports: (
        reports | {"eval": reports["eval"] | {"determinism_failures": 1}}
    ),
    "audit_chain": lambda reports: reports | {"eval": reports["eval"] | {"audit_valid": False}},
    "critical_mutation_score": lambda reports: (
        reports | {"mutation": reports["mutation"] | {"mutation_score": 0.99}}
    ),
    "critical_mutation_survivors": lambda reports: (
        reports | {"mutation": reports["mutation"] | {"survived": ["M01_SOMETHING"]}}
    ),
    "migration_table_parity": lambda reports: (
        reports | {"migration": reports["migration"] | {"table_set_match": False}}
    ),
    "migration_required_tables": lambda reports: (
        reports | {"migration": reports["migration"] | {"tables_actual": ["audit_events"]}}
    ),
    "migration_audit_head": lambda reports: (
        reports | {"migration": reports["migration"] | {"audit_head_seeded": False}}
    ),
    "migration_fts5": lambda reports: (
        reports | {"migration": reports["migration"] | {"sqlite_fts5_present": False}}
    ),
    "scale_status": lambda reports: reports | {"scale": reports["scale"] | {"status": "FAIL"}},
    "scale_metric_provenance": lambda reports: (
        reports | {"scale": reports["scale"] | {"metric_status": "ASSUMED"}}
    ),
    "scale_top1": lambda reports: (
        reports
        | {
            "scale": reports["scale"]
            | {"results": reports["scale"]["results"] | {"top1_recall": 0.1}}
        }
    ),
    "scale_candidate_bound": lambda reports: (
        reports
        | {
            "scale": reports["scale"]
            | {"results": reports["scale"]["results"] | {"candidate_count": 10**6}}
        }
    ),
    "scale_local_p95": lambda reports: (
        reports
        | {
            "scale": reports["scale"]
            | {"results": reports["scale"]["results"] | {"query_latency_ms_p95": 10**6}}
        }
    ),
}


def test_every_gate_predicate_has_a_negative_control() -> None:
    """The inventory comes from the code, so a new predicate lands here uncovered."""
    missing = set(operational_predicates()) - set(OPERATIONAL_BREAKERS)
    stale = set(OPERATIONAL_BREAKERS) - set(operational_predicates())

    assert missing == set(), (
        f"operational predicates with no case that makes them false: {sorted(missing)} — "
        "a gate that has never been shown to fail is not evidence about the system (§2.8)"
    )
    assert stale == set(), f"negative controls for predicates that no longer exist: {sorted(stale)}"


def test_the_passing_artifacts_actually_pass() -> None:
    """The dual: a negative control over inputs that fail anyway proves nothing."""
    result = evaluate(passing_reports())

    assert result.status == "PASS", result.failures


@pytest.mark.parametrize("predicate", sorted(OPERATIONAL_BREAKERS))
def test_the_operational_gate_can_fail_on_each_predicate(predicate: str) -> None:
    broken = OPERATIONAL_BREAKERS[predicate](_stamped(passing_reports()))

    result = evaluate(deepcopy(broken))

    assert result.status == "FAIL", predicate
    assert result.checks.get(predicate) is False or predicate in result.failures, (
        f"{predicate} did not report itself as the reason: {result.failures}"
    )


def _passing_recovery() -> dict[str, Any]:
    """A drill report shaped like the one measure_recovery.py writes in CI.

    ci-fixture, not production-like: the fixture is what CI can produce, and the
    predicates assert that it was measured and declared honestly, not that its
    numbers meet an objective nobody has declared (admission ground 2.9).
    """
    return {
        "schema_version": 1,
        "scale_class": "ci-fixture",
        "rto_seconds": 12.5,
        "rpo_seconds": 0.0,
        "lost_events": 0,
        # Повна втрата, а не лише фікстурна підмножина. Без цього поля вирок
        # відмовляє: невиміряне не є нулем.
        "lost_documents_total": 0,
        "provenance": {
            "backup_bytes": 40960,
            "plaintext_bytes": 131072,
            "document_rows": 2,
            "audit_event_rows": 7,
            "engine_version": "170004",
            "measured_at": "2026-08-05T09:00:00+00:00",
            "writes_after_backup": 5,
        },
    }


def _assurance_inputs() -> dict[str, Any]:
    reports = _stamped(passing_reports())
    reports["operational"] = {"status": "PASS"}
    reports["mutation"]["mutation_score_over_catalogue"] = 1.0
    reports["recovery"] = _passing_recovery()
    return {
        "policy": {
            "assurance": {
                "minimum_tests": 100,
                "minimum_executed_tests": 100,
                "minimum_line_rate": 0.80,
                "minimum_branch_rate": 0.60,
                "required_quality_tools": ["ruff", "mypy"],
            }
        },
        "junit": {"tests": "400", "skipped": "1", "failures": "0", "errors": "0"},
        "coverage": {"line-rate": "0.90", "branch-rate": "0.80"},
        "reports": reports,
        "quality": {
            "tools": {
                "ruff": {"status": "PASS", "exit_code": 0},
                "mypy": {"status": "PASS", "exit_code": 0},
            }
        },
        "source_digest": TREE_DIGEST,
    }


ASSURANCE_BREAKERS: dict[str, Any] = {
    "tests_executed": lambda inputs: inputs | {"junit": inputs["junit"] | {"tests": "0"}},
    "tests_not_mostly_skipped": lambda inputs: (
        inputs | {"junit": inputs["junit"] | {"skipped": "399"}}
    ),
    "tests_outcome": lambda inputs: inputs | {"junit": inputs["junit"] | {"failures": "1"}},
    "coverage_line": lambda inputs: (
        inputs | {"coverage": inputs["coverage"] | {"line-rate": "0.10"}}
    ),
    "coverage_branch": lambda inputs: (
        inputs | {"coverage": inputs["coverage"] | {"branch-rate": "0.10"}}
    ),
    "quality_tooling_executed": lambda inputs: inputs | {"quality": None},
    "reports_present": lambda inputs: (
        inputs | {"reports": {k: v for k, v in inputs["reports"].items() if k != "mutation"}}
    ),
    "evidence_provenance": lambda inputs: inputs | {"source_digest": None},
    "eval": lambda inputs: (
        inputs
        | {"reports": inputs["reports"] | {"eval": inputs["reports"]["eval"] | {"pass_rate": 0.5}}}
    ),
    "mutation": lambda inputs: (
        inputs
        | {
            "reports": inputs["reports"]
            | {"mutation": inputs["reports"]["mutation"] | {"mutation_score_over_catalogue": 0.99}}
        }
    ),
    "migration": lambda inputs: (
        inputs
        | {
            "reports": inputs["reports"]
            | {"migration": inputs["reports"]["migration"] | {"table_set_match": False}}
        }
    ),
    "scale": lambda inputs: (
        inputs
        | {
            "reports": inputs["reports"]
            | {"scale": inputs["reports"]["scale"] | {"status": "FAIL"}}
        }
    ),
    "operational": lambda inputs: (
        inputs | {"reports": inputs["reports"] | {"operational": {"status": "FAIL"}}}
    ),
    # No drill at all — the state every release before 2026-08-05 was assembled in.
    "recovery_drill_executed": lambda inputs: (
        inputs | {"reports": {k: v for k, v in inputs["reports"].items() if k != "recovery"}}
    ),
    # A duration with nothing to interpret it against: how much data, on what engine.
    "recovery_provenance_complete": lambda inputs: (
        inputs
        | {
            "reports": inputs["reports"]
            | {
                "recovery": inputs["reports"]["recovery"]
                | {
                    "provenance": {
                        k: v
                        for k, v in inputs["reports"]["recovery"]["provenance"].items()
                        if k != "document_rows"
                    }
                }
            }
        }
    ),
    # Втрата, більша за вікно, яке навчання створило навмисно. Доти це число
    # вимірювалось, друкувалось і не судилось: відновлення, що втратило п'ять тисяч
    # документів, і бездоганне отримували ОДИН вирок.
    "recovery_loss_explained": lambda inputs: (
        inputs
        | {
            "reports": inputs["reports"]
            | {"recovery": inputs["reports"]["recovery"] | {"lost_documents_total": 5000}}
        }
    ),
    # The TEVV failure mode transplanted: a fixture relabelled as the real thing.
    "recovery_scale_not_overstated": lambda inputs: (
        inputs
        | {
            "reports": inputs["reports"]
            | {"recovery": inputs["reports"]["recovery"] | {"scale_class": "production-like"}}
        }
    ),
}


def test_every_assurance_predicate_has_a_negative_control() -> None:
    missing = set(assurance_predicates()) - set(ASSURANCE_BREAKERS)
    stale = set(ASSURANCE_BREAKERS) - set(assurance_predicates())

    assert missing == set(), (
        f"assurance predicates with no case that makes them false: {sorted(missing)}"
    )
    assert stale == set(), f"negative controls for predicates that no longer exist: {sorted(stale)}"


def test_the_passing_assurance_inputs_actually_pass() -> None:
    inputs = _assurance_inputs()

    result = evaluate_assurance(
        inputs["policy"],
        inputs["junit"],
        inputs["coverage"],
        inputs["reports"],
        inputs["quality"],
        inputs["source_digest"],
    )

    assert result.status == "PASS", result.failures


@pytest.mark.parametrize("predicate", sorted(ASSURANCE_BREAKERS))
def test_the_assurance_aggregator_can_fail_on_each_predicate(predicate: str) -> None:
    inputs = ASSURANCE_BREAKERS[predicate](_assurance_inputs())

    result = evaluate_assurance(
        inputs["policy"],
        inputs["junit"],
        inputs["coverage"],
        inputs["reports"],
        inputs["quality"],
        inputs["source_digest"],
    )

    assert result.status == "FAIL", predicate
    assert result.checks.get(predicate) is False or any(
        predicate in reason for reason in result.failures
    ), f"{predicate} did not report itself as the reason: {result.failures}"
