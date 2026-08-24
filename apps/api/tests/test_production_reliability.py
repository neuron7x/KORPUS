from __future__ import annotations

import base64
import hashlib
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from korpus.application.assurance_evidence import evaluate_attested_reliability
from korpus.application.production_reliability import evaluate_reliability_evidence


def _evidence() -> tuple[dict, dict, dict, dict]:
    internal = {"status": "PASS", "source_tree_sha256": "s", "release": "v"}
    chaos = {"cases": [{"verdict": "expected"} for _ in range(8)]}
    phase = {
        "requests": 10,
        "concurrency": 4,
        "p50_seconds": 0.1,
        "p95_seconds": 0.2,
        "p99_seconds": 0.3,
        "statuses": {"200": 10},
        "refusal_reasons": {},
        "decisions": {},
    }
    load = {
        "source_tree_sha256": "s",
        "release": "v",
        "environment_class": "PRODUCTION_LIKE",
        "cold_first_request": {"seconds": 0.1, "status": "200"},
        "load": dict(phase),
        "spike": dict(phase),
        "soak": dict(phase),
    }
    recovery = {
        "status": "PASS",
        "source_tree_sha256": "s",
        "release": "v",
        "environment_class": "PRODUCTION_LIKE",
    }
    return internal, chaos, load, recovery


def _signed(data: bytes, name: str) -> tuple[dict, str]:
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    fingerprint = hashlib.sha256(public).hexdigest()
    return {
        "algorithm": "Ed25519",
        "release": "v",
        "manifest": name,
        "manifest_sha256": hashlib.sha256(data).hexdigest(),
        "public_key_pem": public.decode(),
        "public_key_sha256": fingerprint,
        "signature_base64": base64.b64encode(key.sign(data)).decode(),
    }, fingerprint


def test_complete_production_like_reliability_evidence_passes_base_predicates() -> None:
    assert all(evaluate_reliability_evidence(*_evidence(), source="s", release="v").values())


def test_production_like_strings_without_attestations_cannot_promote_reliability() -> None:
    internal, chaos, load, recovery = _evidence()
    load_bytes = (json.dumps(load, sort_keys=True) + "\n").encode()
    recovery_bytes = (json.dumps(recovery, sort_keys=True) + "\n").encode()
    checks, _, _ = evaluate_attested_reliability(
        internal,
        chaos,
        load,
        recovery,
        source="s",
        release="v",
        load_bytes=load_bytes,
        recovery_bytes=recovery_bytes,
        load_attestation={},
        recovery_attestation={},
        trusted=set(),
    )
    assert checks["load_environment"] and checks["recovery_environment"]
    assert not checks["load_attestation_verified"] and not checks["recovery_attestation_verified"]
    assert not checks["load_trusted_signer"] and not checks["recovery_trusted_signer"]


def test_pretrusted_attestations_clear_reliability_trust_boundary() -> None:
    internal, chaos, load, recovery = _evidence()
    load_bytes = (json.dumps(load, sort_keys=True) + "\n").encode()
    recovery_bytes = (json.dumps(recovery, sort_keys=True) + "\n").encode()
    load_att, load_fp = _signed(load_bytes, "load-probe.json")
    recovery_att, recovery_fp = _signed(recovery_bytes, "recovery-report.json")
    checks, _, _ = evaluate_attested_reliability(
        internal,
        chaos,
        load,
        recovery,
        source="s",
        release="v",
        load_bytes=load_bytes,
        recovery_bytes=recovery_bytes,
        load_attestation=load_att,
        recovery_attestation=recovery_att,
        trusted={load_fp, recovery_fp},
    )
    assert all(checks.values()), checks


def test_local_load_and_fixture_recovery_cannot_promote_production_even_if_signed() -> None:
    internal, chaos, load, recovery = _evidence()
    load["environment_class"] = "LOCAL_DEV"
    recovery["environment_class"] = "CI_FIXTURE"
    checks = evaluate_reliability_evidence(internal, chaos, load, recovery, source="s", release="v")
    assert checks["load_environment"] is False and checks["recovery_environment"] is False


def test_reliability_evidence_from_another_tree_is_rejected() -> None:
    internal, chaos, load, recovery = _evidence()
    load["source_tree_sha256"] = "old"
    recovery["source_tree_sha256"] = "old"
    checks = evaluate_reliability_evidence(internal, chaos, load, recovery, source="s", release="v")
    assert checks["load_source_bound"] is False and checks["recovery_source_bound"] is False


def test_signed_bad_load_cannot_pass_reliability_quality_predicates() -> None:
    internal, chaos, load, recovery = _evidence()
    load["soak"]["statuses"] = {"503": 10}
    load["soak"]["refusal_reasons"] = {"subject_share_exhausted": 10}
    load_bytes = (json.dumps(load, sort_keys=True) + "\n").encode()
    recovery_bytes = (json.dumps(recovery, sort_keys=True) + "\n").encode()
    load_att, load_fp = _signed(load_bytes, "load-probe.json")
    recovery_att, recovery_fp = _signed(recovery_bytes, "recovery-report.json")
    checks, _, _ = evaluate_attested_reliability(
        internal,
        chaos,
        load,
        recovery,
        source="s",
        release="v",
        load_bytes=load_bytes,
        recovery_bytes=recovery_bytes,
        load_attestation=load_att,
        recovery_attestation=recovery_att,
        trusted={load_fp, recovery_fp},
    )
    assert checks["load_attestation_verified"] and checks["load_trusted_signer"]
    assert checks["load_slo_no_5xx_rated"] is False
    assert checks["load_slo_no_subject_throttle_rated"] is False
    assert not all(checks.values())
