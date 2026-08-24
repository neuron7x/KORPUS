"""A name in `signed_by` is a string this repository chose.

The attestation contract checks that the document exists, the digest matches, the date
is real, and an assessment is not self-signed by name. Everything in that list is
satisfied by anyone with write access here: write a PDF, compute its sha256, type an
organisation's name. Nothing so far is evidence that the named party saw anything.

An Ed25519 signature over the attestation's own content is. The private key is not in
this tree and cannot be; substituting the public key is a visible edit to a file the
desired-state manifest pins, which is a different act with a different trace.

Role is checked with identity, because a corpus owner signing the independent security
assessment is the same substitution §2.5 was raised against, moved one level up. And
the ground id is inside the signed payload, so a signature obtained for the TEVV
measurement cannot be moved onto the security assessment.

What none of this proves — that the key belongs to who the registry says, and that the
holder had authority — is settled at enrolment, by whoever accepts the system. Stated
here because a mechanism that quietly implied otherwise would be worse than none.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from korpus.application.admission import evaluate_admission
from korpus.security.attestors import AttestorKey, AttestorRegistry

ROOT = Path(__file__).resolve().parents[3]
REGISTER = ROOT / "config/operations/admission-grounds.json"


def _keypair() -> tuple[Ed25519PrivateKey, str]:
    private = Ed25519PrivateKey.generate()
    raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return private, base64.b64encode(raw).decode("ascii")


def _registry(role: str = "external_assessor") -> tuple[AttestorRegistry, Ed25519PrivateKey]:
    private, public_b64 = _keypair()
    registry = AttestorRegistry(
        registry_id="attestors-test",
        keys={
            "assessor-key": AttestorKey(
                key_id="assessor-key",
                organisation="Незалежна організація з безпекової оцінки",
                role=role,
                public_key_b64=public_b64,
                enrolled_by="власник процесу",
            )
        },
    )
    return registry, private


def _attestation(
    private: Ed25519PrivateKey | None,
    *,
    ground_id: str,
    document_sha256: str,
    signed_by: str = "Незалежна організація з безпекової оцінки",
    signed_at: str = "2026-08-01",
    key_id: str = "assessor-key",
) -> dict[str, Any]:
    attestation: dict[str, Any] = {
        "document": "docs/operations/ATTESTATION_TEMPLATES.md",
        "sha256": document_sha256,
        "signed_by": signed_by,
        "signed_at": signed_at,
        "key_id": key_id,
    }
    if private is not None:
        payload = AttestorRegistry.signed_payload(
            ground_id=ground_id,
            document_sha256=document_sha256,
            signed_by=signed_by,
            signed_at=signed_at,
        )
        attestation["signature_b64"] = base64.b64encode(private.sign(payload)).decode("ascii")
    return attestation


def _document_digest() -> str:
    return hashlib.sha256(
        (ROOT / "docs/operations/ATTESTATION_TEMPLATES.md").read_bytes()
    ).hexdigest()


def _verify(registry: AttestorRegistry, attestation: dict[str, Any], kind: str) -> list[str]:
    return registry.verify(
        ground_id="2.5",
        ground_kind=kind,
        attestation=attestation,
        document_sha256=_document_digest(),
    )


def test_a_correctly_signed_attestation_verifies() -> None:
    """The dual: a mechanism that refuses everything settles nothing."""
    registry, private = _registry()
    attestation = _attestation(private, ground_id="2.5", document_sha256=_document_digest())

    assert _verify(registry, attestation, "external_assessment") == []


def test_an_unsigned_attestation_is_refused() -> None:
    """The state the register was in until now: four consistent fields, no signature."""
    registry, _ = _registry()
    attestation = _attestation(None, ground_id="2.5", document_sha256=_document_digest())

    problems = _verify(registry, attestation, "external_assessment")

    assert problems and "carries no signature" in problems[0]


def test_a_signature_from_an_unenrolled_key_is_refused() -> None:
    registry, _ = _registry()
    _, other_private = _registry()
    attestation = _attestation(other_private, ground_id="2.5", document_sha256=_document_digest())
    attestation["key_id"] = "some-key-nobody-enrolled"

    problems = _verify(registry, attestation, "external_assessment")

    assert problems and "unknown or revoked" in problems[0]


def test_a_signature_from_a_revoked_key_is_refused() -> None:
    """Revocation is where the cryptography is fine and the answer is still no."""
    registry, private = _registry()
    registry.keys["assessor-key"] = registry.keys["assessor-key"].model_copy(
        update={"revoked": True}
    )
    attestation = _attestation(private, ground_id="2.5", document_sha256=_document_digest())

    problems = _verify(registry, attestation, "external_assessment")

    assert problems and "unknown or revoked" in problems[0]


def test_a_corpus_owner_cannot_sign_the_independent_assessment() -> None:
    """§2.5 raised against the assessed party attesting to itself, one level up."""
    registry, private = _registry(role="corpus_owner")
    attestation = _attestation(private, ground_id="2.5", document_sha256=_document_digest())

    problems = _verify(registry, attestation, "external_assessment")

    assert problems and "may not attest" in problems[0]


def test_an_assessor_key_may_sign_a_measurement() -> None:
    """The roles are a lattice, not a partition: §2.6 accepts either party."""
    registry, private = _registry()
    attestation = _attestation(private, ground_id="2.5", document_sha256=_document_digest())

    assert _verify(registry, attestation, "measurement") == []


def test_a_signature_over_a_different_document_is_refused() -> None:
    """Otherwise one signature clears every ground that names any document."""
    registry, private = _registry()
    attestation = _attestation(private, ground_id="2.5", document_sha256="c" * 64)

    problems = _verify(registry, attestation, "external_assessment")

    assert problems and "does not verify" in problems[0]


def test_a_signature_obtained_for_another_ground_cannot_be_moved() -> None:
    """A signed TEVV report must not clear the security assessment."""
    registry, private = _registry()
    attestation = _attestation(private, ground_id="2.6", document_sha256=_document_digest())

    problems = _verify(registry, attestation, "external_assessment")

    assert problems and "does not verify" in problems[0]


def test_altering_the_signer_name_after_signing_is_refused() -> None:
    registry, private = _registry()
    attestation = _attestation(private, ground_id="2.5", document_sha256=_document_digest())
    attestation["signed_by"] = "хтось інший"

    problems = _verify(registry, attestation, "external_assessment")

    assert problems and "does not verify" in problems[0]


def test_a_signature_outside_the_key_validity_window_is_refused() -> None:
    registry, private = _registry()
    registry.keys["assessor-key"] = registry.keys["assessor-key"].model_copy(
        update={"valid_from": date(2026, 9, 1)}
    )
    attestation = _attestation(private, ground_id="2.5", document_sha256=_document_digest())

    problems = _verify(registry, attestation, "external_assessment")

    assert problems and "predates" in problems[0]


def test_a_key_of_the_wrong_length_cannot_be_enrolled() -> None:
    with pytest.raises(ValueError, match="must be 32 bytes"):
        AttestorKey(
            key_id="short",
            organisation="Org",
            role="external_assessor",
            public_key_b64=base64.b64encode(b"x" * 48).decode("ascii"),
            enrolled_by="власник процесу",
        )


def test_an_unknown_role_cannot_be_enrolled() -> None:
    _, public_b64 = _keypair()

    with pytest.raises(ValueError, match="unknown attestor role"):
        AttestorKey(
            key_id="odd",
            organisation="Org",
            role="whoever",
            public_key_b64=public_b64,
            enrolled_by="власник процесу",
        )


def test_the_admission_verdict_refuses_a_clearance_with_no_signature() -> None:
    """End to end: the register cannot clear a ground without a verifiable signature."""
    register = json.loads(REGISTER.read_text(encoding="utf-8"))
    forged = copy.deepcopy(register)
    for ground in forged["grounds"]:
        if ground["id"] == "2.5":
            ground["status"] = "cleared"
            ground["evidence"] = ["docs/operations/ATTESTATION_TEMPLATES.md"]
            ground["attestation"] = {
                "document": "docs/operations/ATTESTATION_TEMPLATES.md",
                "sha256": _document_digest(),
                "signed_by": "Незалежна організація з безпекової оцінки",
                "signed_at": "2026-08-01",
            }

    registry, _ = _registry()
    verdict = evaluate_admission(ROOT, forged, registry)

    assert verdict.production_authorized is False
    # Specifically "no signature", not merely "some registry problem": accepting either
    # message let a mutant that skips the signature check entirely pass this test, since
    # the fallback path also mentions the registry. Probed 2026-08-05 (M142 survived).
    assert any("carries no signature" in problem for problem in verdict.problems), (
        verdict.problems
    )
