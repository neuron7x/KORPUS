from __future__ import annotations

from korpus.application.production_reliability import evaluate_reliability_evidence


def _evidence() -> tuple[dict, dict, dict, dict]:
    internal = {"status": "PASS", "source_tree_sha256": "s", "release": "v"}
    chaos = {"cases": [{"verdict": "expected"} for _ in range(8)]}
    phase = {"requests": 10, "p50_seconds": 0.1, "p95_seconds": 0.2, "p99_seconds": 0.3}
    load = {"source_tree_sha256": "s", "release": "v", "environment_class": "PRODUCTION_LIKE",
            "load": phase, "spike": phase, "soak": phase}
    recovery = {"status": "PASS", "source_tree_sha256": "s", "release": "v",
                "environment_class": "PRODUCTION_LIKE"}
    return internal, chaos, load, recovery


def test_complete_production_like_reliability_evidence_passes_every_predicate() -> None:
    checks = evaluate_reliability_evidence(*_evidence(), source="s", release="v")
    assert all(checks.values()), checks


def test_local_load_and_fixture_recovery_cannot_promote_production() -> None:
    internal, chaos, load, recovery = _evidence()
    load["environment_class"] = "LOCAL_DEV"
    recovery["environment_class"] = "CI_FIXTURE"
    checks = evaluate_reliability_evidence(internal, chaos, load, recovery, source="s", release="v")
    assert checks["load_environment"] is False
    assert checks["recovery_environment"] is False


def test_reliability_evidence_from_another_tree_is_rejected() -> None:
    internal, chaos, load, recovery = _evidence()
    load["source_tree_sha256"] = "old"
    recovery["source_tree_sha256"] = "old"
    checks = evaluate_reliability_evidence(internal, chaos, load, recovery, source="s", release="v")
    assert checks["load_source_bound"] is False
    assert checks["recovery_source_bound"] is False
