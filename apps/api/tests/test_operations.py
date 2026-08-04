from __future__ import annotations

import json
from pathlib import Path

import pytest
from korpus.application.operations import (
    GateResult,
    OperationalReleaseGate,
    jensen_shannon_divergence,
)
from korpus.application.provenance import PROVENANCE_KEY

POLICY = Path("config/operations/reference-v5.json")
TREE_DIGEST = "c" * 64


def evaluate(reports: dict) -> GateResult:
    """Evaluate with provenance satisfied, so other predicates are what is tested.

    Provenance itself is attacked in test_evidence_provenance.py.
    """

    for report in reports.values():
        report.setdefault(
            PROVENANCE_KEY,
            {
                "schema_version": 1,
                "source_digest": TREE_DIGEST,
                "generator": "test",
                "generated_at": "2026-08-04T00:00:00+00:00",
            },
        )
    return OperationalReleaseGate.load(POLICY).evaluate(reports, source_digest=TREE_DIGEST)


def passing_reports() -> dict:
    return {
        "eval": {
            "pass_rate": 1.0,
            "citation_failures": 0,
            "leakage_failures": 0,
            "leakage_checks": 26,
            "determinism_failures": 0,
            "audit_valid": True,
        },
        "mutation": {"mutation_score": 1.0, "survived": []},
        "migration": {
            "table_set_match": True,
            "audit_head_seeded": True,
            "sqlite_fts5_present": True,
            "tables_actual": [
                "audit_anchor_outbox",
                "audit_events",
                "audit_heads",
                "document_compartments",
                "documents",
                "document_versions",
                "evidence_spans",
                "ingestion_jobs",
                "span_embeddings",
            ],
        },
        "scale": {
            "status": "PASS",
            "metric_status": "ANCHORED_LOCAL_MEASUREMENT",
            "results": {
                "top1_recall": 1.0,
                "candidate_count": 256,
                "query_latency_ms_p95": 49.9,
            },
        },
    }


def test_js_divergence_is_bounded_symmetric_and_identity_zero():
    assert jensen_shannon_divergence([1, 2, 3], [1, 2, 3]) == pytest.approx(0.0)
    forward = jensen_shannon_divergence([9, 1], [1, 9])
    reverse = jensen_shannon_divergence([1, 9], [9, 1])
    assert forward == pytest.approx(reverse)
    assert 0 < forward <= 1


@pytest.mark.parametrize(
    "left,right", [([], []), ([0, 0], [1, 0]), ([1, -1], [1, 1]), ([1], [1, 2])]
)
def test_js_divergence_rejects_undefined_inputs(left, right):
    with pytest.raises(ValueError):
        jensen_shannon_divergence(left, right)


def test_operational_gate_passes_encoded_engineering_predicates_only():
    result = evaluate(passing_reports())
    assert result.passed is True
    assert result.production_authorized is False
    assert all(result.checks.values())


@pytest.mark.parametrize(
    "section,key,value,failed_check",
    [
        ("eval", "leakage_failures", 1, "access_noninterference"),
        ("eval", "citation_failures", 1, "citation_integrity"),
        ("mutation", "mutation_score", 0.99, "critical_mutation_score"),
    ],
)
def test_operational_gate_fails_closed_on_trust_regression(section, key, value, failed_check):
    reports = passing_reports()
    reports[section][key] = value
    result = evaluate(reports)
    assert result.passed is False
    assert failed_check in result.failures


def test_operational_policy_is_valid_json_and_explicitly_not_authorization():
    policy = json.loads(POLICY.read_text())
    assert policy["status"] == "ENGINEERING_GATE_ONLY_NOT_PRODUCTION_AUTHORIZATION"
