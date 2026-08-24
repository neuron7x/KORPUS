from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from korpus.application.production_assurance import evaluate_production_assurance
from korpus.application.production_report_verification import verify_production_report


def _profile() -> dict[str, object]:
    return {
        "required_gates": [
            "engineering",
            "tevv",
            "observability",
            "state_contracts",
            "authorization",
            "redteam",
            "reliability",
            "inference_security",
            "postgres_security",
            "supply_chain",
            "exact_environment",
            "mutation",
        ],
        "external_requirements": {
            "redteam_evidence_class": "EXTERNAL_INDEPENDENT",
            "redteam_attestation_verified": True,
            "redteam_trusted_signer_required": True,
            "tevv_environment_classes": ["PRODUCTION_LIKE", "PRODUCTION"],
            "tevv_independent_class": "EXTERNAL_INDEPENDENT",
            "tevv_trusted_assessor_required": True,
            "postgres_backend": "postgresql",
            "supply_chain_completeness": "COMPLETE",
            "mutation_scope": "FULL_CATALOGUE",
        },
    }


def _sound_gates(source: str, release: str) -> dict[str, dict[str, object]]:
    gates: dict[str, dict[str, object]] = {}
    for gate in _profile()["required_gates"]:
        gates[str(gate)] = {
            "schema": "korpus.production-gate.v1",
            "gate_id": gate,
            "status": "PASS",
            "source_tree_sha256": source,
            "release": release,
            "checks": {},
            "failures": [],
        }
    gates["redteam"].update(
        {
            "evidence_class": "EXTERNAL_INDEPENDENT",
            "attestation_verified": True,
            "trusted_signer": True,
        }
    )
    gates["tevv"]["environment_class"] = "PRODUCTION_LIKE"
    gates["tevv"]["checks"] = {"independent_class": True, "assessor_trusted_signer": True}
    gates["postgres_security"]["backend"] = "postgresql"
    gates["supply_chain"]["completeness"] = "COMPLETE"
    gates["mutation"]["scope"] = "FULL_CATALOGUE"
    return gates


def _report(
    profile: dict[str, object], gates: dict[str, dict[str, object]], source: str, release: str
):
    verdict = evaluate_production_assurance(profile, gates, source_digest=source, release=release)
    gate_hashes = {
        name: hashlib.sha256(json.dumps(gate, sort_keys=True).encode()).hexdigest()
        for name, gate in gates.items()
    }
    report = {
        "schema": "korpus.production-assurance.v1",
        "status": verdict.status,
        "release": release,
        "source_tree_sha256": source,
        "profile_sha256": "profile-sha",
        "checks": dict(verdict.checks),
        "failures": list(verdict.failures),
        "gate_sha256": gate_hashes,
        "gates": deepcopy(gates),
        "production_authorized": verdict.passed,
    }
    return report, gate_hashes


def _verify(report, profile, gates, source, release, gate_hashes, *, attested=True, trusted=True):
    return verify_production_report(
        report,
        profile,
        gates,
        source=source,
        release=release,
        profile_sha256="profile-sha",
        gate_sha256=gate_hashes,
        attestation_verified=attested,
        trusted_signer=trusted,
    )


def test_sound_recomputed_report_with_trusted_attestation_passes() -> None:
    source, release, profile = "a" * 64, "v9.9.9", _profile()
    gates = _sound_gates(source, release)
    report, hashes = _report(profile, gates, source, release)
    assert all(_verify(report, profile, gates, source, release, hashes).values())


def test_forged_pass_report_cannot_override_failing_current_gate() -> None:
    source, release, profile = "b" * 64, "v9.9.9", _profile()
    sound = _sound_gates(source, release)
    report, _ = _report(profile, sound, source, release)
    current = deepcopy(sound)
    current["postgres_security"]["status"] = "FAIL"
    current_hashes = {
        name: hashlib.sha256(json.dumps(gate, sort_keys=True).encode()).hexdigest()
        for name, gate in current.items()
    }
    checks = _verify(report, profile, current, source, release, current_hashes)
    assert checks["recomputed_pass"] is False
    assert checks["production_authorized"] is False
    assert checks["embedded_gates_current"] is False


def test_stale_gate_hashes_are_rejected_even_when_gate_payloads_match() -> None:
    source, release, profile = "c" * 64, "v9.9.9", _profile()
    gates = _sound_gates(source, release)
    report, hashes = _report(profile, gates, source, release)
    hashes = dict(hashes)
    hashes["engineering"] = "0" * 64
    checks = _verify(report, profile, gates, source, release, hashes)
    assert checks["gate_hashes_current"] is False


def test_unsigned_or_untrusted_production_assurance_report_is_rejected() -> None:
    source, release, profile = "d" * 64, "v9.9.9", _profile()
    gates = _sound_gates(source, release)
    report, hashes = _report(profile, gates, source, release)
    assert (
        _verify(report, profile, gates, source, release, hashes, attested=False)[
            "assurance_attestation_verified"
        ]
        is False
    )
    assert (
        _verify(report, profile, gates, source, release, hashes, trusted=False)[
            "assurance_trusted_signer"
        ]
        is False
    )
