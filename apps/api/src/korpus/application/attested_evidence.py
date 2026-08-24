from __future__ import annotations

import base64
import hashlib
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


@dataclass(frozen=True)
class AttestationVerdict:
    checks: Mapping[str, bool]
    fingerprint: str

    @property
    def cryptographically_valid(self) -> bool:
        return all(value for name, value in self.checks.items() if name != "trusted_signer")

    @property
    def trusted_signer(self) -> bool:
        return bool(self.checks.get("trusted_signer"))

    @property
    def valid(self) -> bool:
        return self.cryptographically_valid and self.trusted_signer


def verify_ed25519_attestation(
    manifest: bytes,
    *,
    manifest_name: str,
    release: str,
    attestation: Mapping[str, Any] | None,
    trusted_fingerprints: Collection[str],
) -> AttestationVerdict:
    payload = attestation if isinstance(attestation, Mapping) else {}
    public_bytes = b""
    signature = b""
    try:
        public_bytes = str(payload.get("public_key_pem", "")).encode("ascii")
        signature = base64.b64decode(str(payload.get("signature_base64", "")), validate=True)
    except (UnicodeEncodeError, ValueError):
        public_bytes, signature = b"", b""
    fingerprint = hashlib.sha256(public_bytes).hexdigest() if public_bytes else ""
    signature_ok = False
    try:
        key = serialization.load_pem_public_key(public_bytes)
        if isinstance(key, Ed25519PublicKey):
            key.verify(signature, manifest)
            signature_ok = True
    except (ValueError, TypeError, InvalidSignature):
        signature_ok = False
    checks = {
        "algorithm": payload.get("algorithm") == "Ed25519",
        "release": payload.get("release") == release,
        "manifest_name": payload.get("manifest") == manifest_name,
        "manifest_sha256": payload.get("manifest_sha256") == hashlib.sha256(manifest).hexdigest(),
        "public_key_sha256": bool(fingerprint) and payload.get("public_key_sha256") == fingerprint,
        "signature": signature_ok,
        "trusted_signer": bool(fingerprint) and fingerprint in set(trusted_fingerprints),
    }
    return AttestationVerdict(checks=checks, fingerprint=fingerprint)
