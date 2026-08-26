from __future__ import annotations

import json
from pathlib import Path

from korpus.application.production_hard_predicates import (
    evaluate_hard_predicates,
    external_predicate_state,
    load_hard_predicate_profile,
)

ROOT = Path(__file__).resolve().parents[3]
PROFILE = ROOT / "config/assurance/production-hard-predicates-v1.json"


def test_all_fourteen_hard_predicates_have_software_execution_or_admission_paths() -> None:
    profile = load_hard_predicate_profile(PROFILE)
    states = evaluate_hard_predicates(ROOT, profile, {})
    assert len(states) == 14
    assert len({state.predicate_id for state in states}) == 14
    assert all(state.software_ready for state in states), [
        (state.predicate_id, state.missing_software_artifacts)
        for state in states
        if not state.software_ready
    ]
    assert not any(state.externally_satisfied for state in states)


def test_missing_external_evidence_never_becomes_production_satisfied() -> None:
    profile = load_hard_predicate_profile(PROFILE)
    states = evaluate_hard_predicates(ROOT, profile, {})
    assert all(state.software_ready for state in states)
    assert all(state.production_satisfied is False for state in states)


def test_exact_environment_requires_every_runtime_check() -> None:
    gate = {
        "status": "PASS",
        "checks": {
            "all_locked_components_installed": True,
            "all_versions_exact": True,
            "no_unmanaged_distributions": True,
            "production_python_exact": True,
            "lock_hashes_present": False,
        },
    }
    ok, failed = external_predicate_state(
        "exact_python_3_12_13_environment", {"exact_environment": gate}
    )
    assert ok is False
    assert failed == ("lock_hashes_present",)


def test_hosted_builder_cannot_be_inferred_from_workflow_presence() -> None:
    ok, failed = external_predicate_state(
        "trusted_hosted_builder",
        {
            "supply_chain": {
                "checks": {
                    "evidence_manifest_bound": True,
                    "evidence_attestation_verified": False,
                    "evidence_trusted_signer": False,
                }
            }
        },
    )
    assert ok is False
    assert set(failed) == {
        "builder_provenance_verified",
        "builder_trusted",
        "builder_attestation_verified",
        "builder_trusted_signer",
    }


def test_profile_ids_match_canonical_hard_predicate_list() -> None:
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    ids = [item["id"] for item in profile["predicates"]]
    assert ids == [
        "external_independent_redteam",
        "live_vulnerability_scanners",
        "live_postgres_rls",
        "real_domain_corpus_tevv",
        "independent_tevv",
        "production_like_tevv_environment",
        "production_like_load",
        "trusted_load_attestation",
        "trusted_recovery_attestation",
        "trusted_hosted_builder",
        "trusted_release_signing",
        "exact_python_3_12_13_environment",
        "pec_human_production_authority",
        "pec_canary_revision_admission",
    ]


def test_postgres_gate_targets_all_exist() -> None:
    import importlib.util

    script = ROOT / "scripts/run_postgres_security_gate.py"
    spec = importlib.util.spec_from_file_location("run_postgres_security_gate", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.TARGETS
    assert all((ROOT / path).is_file() for path in module.TARGETS), module.TARGETS


def test_stale_postgres_gate_cannot_satisfy_a_current_hard_predicate() -> None:
    gate = {
        "backend": "postgresql",
        "release": "v0.9.7",
        "source_tree_sha256": "a" * 64,
        "checks": {
            "target_files_present": True,
            "grant_contract_static": True,
            "postgres_runtime_available": True,
            "postgres_adversarial_suite": True,
        },
    }

    ok, failed = external_predicate_state(
        "live_postgres_rls",
        {"postgres_security": gate},
        current_source_sha256="b" * 64,
        current_release="v0.9.7",
    )

    assert ok is False
    assert failed == ("gate_source_bound",)


def test_hosted_release_node_matches_pinned_web_build_runtime() -> None:
    import re

    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "apps/web/Dockerfile").read_text(encoding="utf-8")
    workflow_match = re.search(r"node-version:\s*([0-9.]+)", workflow)
    image_match = re.search(r"ARG NODE_IMAGE=node:([0-9.]+)-alpine", dockerfile)
    assert workflow_match is not None and image_match is not None
    assert workflow_match.group(1) == image_match.group(1)
