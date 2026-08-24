from __future__ import annotations

from scripts.run_external_gate_campaign import _cause


def capabilities(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "python": "3.13.5",
        "tools": {name: None for name in ("docker", "podman", "psql", "postgres", "trivy", "gitleaks", "grype", "syft", "terraform", "cosign")},
        "test_database_url": False,
        "trusted_builder_id": False,
    }
    value.update(overrides)
    return value


def test_campaign_does_not_confuse_missing_postgres_with_executed_failure() -> None:
    assert _cause("live_postgres_rls", False, {"status": "FAIL"}, capabilities()) == "RUNTIME_UNAVAILABLE"


def test_campaign_preserves_independence_as_a_proof_property() -> None:
    assert _cause("independent_tevv", False, {}, capabilities()) == "INDEPENDENCE_REQUIRED"


def test_campaign_marks_satisfied_predicate_pass_before_capability_diagnosis() -> None:
    assert _cause("live_vulnerability_scanners", True, {}, capabilities()) == "PASS"
