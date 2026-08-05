"""Who may sign an attestation, and proof that they did.

The attestation contract added on 2026-08-05 checks that the attested document exists,
that its digest matches, that the date is real and past, and that an independent
assessment is not signed by the party being assessed. Its own register records what it
does not prove: "it verifies no cryptographic signature and knows nothing about whether
a signatory holds the authority to sign".

That gap is not small. Everything up to here is satisfied by anyone with write access
to this repository: write a PDF, compute its sha256, type an organisation's name into
`signed_by`. The name is a string the same commit chose. So the fields are consistent
with each other and with a document, and none of it is evidence that the named party
saw anything.

An Ed25519 signature over the attestation's own content closes it. The private key is
not in this tree and cannot be; the public key is, and substituting it is a visible
edit to a file whose digest the desired-state manifest pins — which is a different act
from typing a name, with a different trace.

Role is checked as well as identity. A key registered for the corpus owner cannot sign
the independent security assessment: §2.5 exists because the party that built the
system cannot attest to it, and letting any registered key clear any ground would put
that back one level up.

What this still does not prove: that the key belongs to who the register says, and that
the holder had authority to sign. Those are established when the key is enrolled — by
whoever accepts the system — and no amount of code here substitutes for it. The
mechanism proves that whoever holds the enrolled private key signed this exact
attestation.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

#: Which class of ground a key may attest to. A corpus owner signing the independent
#: security assessment is the substitution §2.5 was raised against.
EXTERNAL_ASSESSOR = "external_assessor"
PROCESS_OWNER = "process_owner"
CORPUS_OWNER = "corpus_owner"
ROLES = frozenset({EXTERNAL_ASSESSOR, PROCESS_OWNER, CORPUS_OWNER})

#: ground kind -> roles entitled to attest it
ROLE_FOR_KIND: dict[str, frozenset[str]] = {
    "external_assessment": frozenset({EXTERNAL_ASSESSOR}),
    "owner_decision": frozenset({PROCESS_OWNER, CORPUS_OWNER}),
    "measurement": frozenset({CORPUS_OWNER, EXTERNAL_ASSESSOR}),
}


class AttestorKey(BaseModel):
    key_id: str = Field(min_length=3, max_length=200)
    organisation: str = Field(min_length=2, max_length=300)
    role: str = Field(min_length=3, max_length=64)
    public_key_b64: str = Field(min_length=40, max_length=100)
    enrolled_by: str = Field(min_length=2, max_length=300)
    valid_from: date | None = None
    valid_until: date | None = None
    revoked: bool = False

    @model_validator(mode="after")
    def validate_key(self) -> AttestorKey:
        if self.role not in ROLES:
            raise ValueError(f"unknown attestor role: {self.role}")
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("attestor key validity interval is invalid")
        raw = base64.b64decode(self.public_key_b64, validate=True)
        if len(raw) != 32:
            raise ValueError("Ed25519 public key must be 32 bytes")
        return self


class AttestorRegistry(BaseModel):
    schema_version: int = Field(default=1, ge=1, le=1)
    registry_id: str = Field(min_length=3, max_length=120)
    keys: dict[str, AttestorKey] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_registry(self) -> AttestorRegistry:
        for identifier, key in self.keys.items():
            if identifier != key.key_id:
                raise ValueError("attestor registry key map does not match key_id")
        return self

    @classmethod
    def load(cls, path: Path, expected_sha256: str | None = None) -> AttestorRegistry:
        raw = path.read_bytes()
        if expected_sha256 and hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise ValueError("attestor registry digest mismatch")
        return cls.model_validate_json(raw)

    @staticmethod
    def signed_payload(
        *, ground_id: str, document_sha256: str, signed_by: str, signed_at: str
    ) -> bytes:
        """Canonical bytes an attestor signs.

        The ground id is inside the signature, so a signature obtained for one ground
        cannot be moved to another — which would otherwise let a signed TEVV report
        clear the independent security assessment.
        """
        return json.dumps(
            {
                "document_sha256": document_sha256,
                "ground_id": ground_id,
                "signed_at": signed_at,
                "signed_by": signed_by,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def verify(
        self,
        *,
        ground_id: str,
        ground_kind: str,
        attestation: dict[str, Any],
        document_sha256: str,
    ) -> list[str]:
        """Problems with the signature on this attestation; empty means it verifies."""
        key_id = str(attestation.get("key_id") or "")
        signature_b64 = str(attestation.get("signature_b64") or "")
        if not key_id or not signature_b64:
            return [
                f"{ground_id}: the attestation carries no signature; a name in "
                "signed_by is a string this repository chose"
            ]
        key = self.keys.get(key_id)
        if key is None or key.revoked:
            return [f"{ground_id}: attestor key is unknown or revoked: {key_id}"]

        entitled = ROLE_FOR_KIND.get(ground_kind, frozenset())
        if key.role not in entitled:
            return [
                f"{ground_id}: a {key.role} may not attest a {ground_kind} ground — "
                f"that needs {' or '.join(sorted(entitled)) or 'no attestation'}"
            ]

        signed_at = str(attestation.get("signed_at") or "")
        try:
            signed = date.fromisoformat(signed_at)
        except ValueError:
            return [f"{ground_id}: signed_at is not an ISO date: {signed_at!r}"]
        if key.valid_from and signed < key.valid_from:
            return [f"{ground_id}: the attestation predates the attestor key validity"]
        if key.valid_until and signed > key.valid_until:
            return [f"{ground_id}: the attestation postdates the attestor key validity"]

        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        payload = self.signed_payload(
            ground_id=ground_id,
            document_sha256=document_sha256,
            signed_by=str(attestation.get("signed_by") or ""),
            signed_at=signed_at,
        )
        public = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(key.public_key_b64, validate=True)
        )
        try:
            public.verify(base64.b64decode(signature_b64, validate=True), payload)
        except (InvalidSignature, ValueError, TypeError):
            return [
                f"{ground_id}: the signature does not verify against the enrolled key "
                f"{key_id}"
            ]
        return []
