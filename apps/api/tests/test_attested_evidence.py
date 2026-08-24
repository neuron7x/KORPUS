from __future__ import annotations

import base64
import hashlib

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from korpus.application.attested_evidence import verify_ed25519_attestation


def _signed(data: bytes, name: str = "evidence.json", release: str = "v1") -> tuple[dict, str]:
    private = Ed25519PrivateKey.generate()
    public_bytes = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    fingerprint = hashlib.sha256(public_bytes).hexdigest()
    return {
        "algorithm": "Ed25519",
        "release": release,
        "manifest": name,
        "manifest_sha256": hashlib.sha256(data).hexdigest(),
        "public_key_pem": public_bytes.decode("ascii"),
        "public_key_sha256": fingerprint,
        "signature_base64": base64.b64encode(private.sign(data)).decode("ascii"),
    }, fingerprint


def test_valid_signature_from_pretrusted_key_is_admitted() -> None:
    data = b'{"environment_class":"PRODUCTION_LIKE"}\n'
    attestation, fingerprint = _signed(data)
    verdict = verify_ed25519_attestation(
        data, manifest_name="evidence.json", release="v1", attestation=attestation,
        trusted_fingerprints={fingerprint},
    )
    assert verdict.valid is True
    assert all(verdict.checks.values())


def test_valid_but_untrusted_self_signature_is_not_trust_evidence() -> None:
    data = b"evidence"
    attestation, _ = _signed(data)
    verdict = verify_ed25519_attestation(
        data, manifest_name="evidence.json", release="v1", attestation=attestation,
        trusted_fingerprints=set(),
    )
    assert verdict.cryptographically_valid is True
    assert verdict.trusted_signer is False
    assert verdict.valid is False


def test_tampered_evidence_breaks_signature_and_digest_binding() -> None:
    original = b"original"
    attestation, fingerprint = _signed(original)
    verdict = verify_ed25519_attestation(
        b"tampered", manifest_name="evidence.json", release="v1", attestation=attestation,
        trusted_fingerprints={fingerprint},
    )
    assert verdict.checks["manifest_sha256"] is False
    assert verdict.checks["signature"] is False
    assert verdict.valid is False


def test_attestation_cannot_be_replayed_for_another_release_or_filename() -> None:
    data = b"bound"
    attestation, fingerprint = _signed(data)
    wrong_release = verify_ed25519_attestation(
        data, manifest_name="evidence.json", release="v2", attestation=attestation,
        trusted_fingerprints={fingerprint},
    )
    wrong_name = verify_ed25519_attestation(
        data, manifest_name="other.json", release="v1", attestation=attestation,
        trusted_fingerprints={fingerprint},
    )
    assert wrong_release.checks["release"] is False
    assert wrong_name.checks["manifest_name"] is False
