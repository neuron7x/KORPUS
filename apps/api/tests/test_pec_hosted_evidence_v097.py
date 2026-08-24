from __future__ import annotations

from korpus.application.pec_hosted_evidence import validate_hosted_evidence

S = "a" * 64


def receipt():
    return {
        "provider": "github-actions",
        "run_id": "123",
        "workflow": "pec-production-evidence",
        "release": "v0.9.7",
        "source_digest": S,
        "local_self_attested": False,
    }


def test_hosted_evidence_accepts_known_ci_provider():
    assert validate_hosted_evidence(receipt(), release="v0.9.7", source_digest=S).valid


def test_hosted_evidence_rejects_local_self_attestation():
    r = receipt()
    r["local_self_attested"] = True
    v = validate_hosted_evidence(r, release="v0.9.7", source_digest=S)
    assert not v.valid and "not_local_self_attested" in v.failures


def test_hosted_evidence_rejects_unknown_provider():
    r = receipt()
    r["provider"] = "local-shell"
    v = validate_hosted_evidence(r, release="v0.9.7", source_digest=S)
    assert not v.valid and "provider" in v.failures


def test_hosted_evidence_rejects_source_drift():
    r = receipt()
    r["source_digest"] = "b" * 64
    v = validate_hosted_evidence(r, release="v0.9.7", source_digest=S)
    assert not v.valid and "source_digest" in v.failures
