from __future__ import annotations

import hashlib
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

from korpus.application.attested_evidence import verify_ed25519_attestation
from korpus.application.final_release_provenance import (
    ReleaseBuildContext,
    builder_provenance_checks,
    release_manifest_checks,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class FinalReleaseVerdict:
    checks: Mapping[str, bool]
    builder_id: str
    builder_signer_fingerprint: str
    release_signer_fingerprint: str

    @property
    def authorized(self) -> bool:
        return all(self.checks.values())

    def as_dict(self) -> dict[str, Any]:
        failures = [name for name, ok in self.checks.items() if not ok]
        return {
            "schema": "korpus.final-production-authorization.v1",
            "status": "PASS" if not failures else "FAIL",
            "production_authorized": not failures,
            "checks": dict(self.checks),
            "failures": failures,
            "builder_id": self.builder_id,
            "builder_signer_fingerprint": self.builder_signer_fingerprint,
            "release_signer_fingerprint": self.release_signer_fingerprint,
        }


def evaluate_final_release(
    *,
    artifact_name: str,
    artifact_bytes: bytes,
    source_manifest_bytes: bytes,
    production_assurance_bytes: bytes,
    production_assurance: Mapping[str, Any],
    release_manifest_name: str,
    release_manifest_bytes: bytes,
    release_manifest: Mapping[str, Any],
    release_attestation: Mapping[str, Any],
    builder_statement_name: str,
    builder_statement_bytes: bytes,
    builder_statement: Mapping[str, Any],
    builder_attestation: Mapping[str, Any],
    build_context: ReleaseBuildContext,
    trusted_release_signers: Collection[str],
    trusted_builder_signers: Collection[str],
    trusted_builder_ids: Collection[str],
) -> FinalReleaseVerdict:
    artifact_sha = _sha(artifact_bytes)
    builder_id, provenance_checks = builder_provenance_checks(
        builder_statement,
        artifact_name,
        artifact_sha,
        _sha(source_manifest_bytes),
        trusted_builder_ids,
        build_context,
    )
    manifest_checks = release_manifest_checks(
        release_manifest,
        artifact_name,
        artifact_sha,
        _sha(source_manifest_bytes),
        _sha(production_assurance_bytes),
        build_context,
    )
    builder_att = verify_ed25519_attestation(
        builder_statement_bytes,
        manifest_name=builder_statement_name,
        release=build_context.release,
        attestation=builder_attestation,
        trusted_fingerprints=trusted_builder_signers,
    )
    release_att = verify_ed25519_attestation(
        release_manifest_bytes,
        manifest_name=release_manifest_name,
        release=build_context.release,
        attestation=release_attestation,
        trusted_fingerprints=trusted_release_signers,
    )
    checks = {
        "production_assurance_pass": production_assurance.get("status") == "PASS",
        "production_assurance_authorized": production_assurance.get("production_authorized")
        is True,
        **manifest_checks,
        **provenance_checks,
        "builder_attestation_verified": builder_att.cryptographically_valid,
        "builder_trusted_signer": builder_att.trusted_signer,
        "release_attestation_verified": release_att.cryptographically_valid,
        "release_trusted_signer": release_att.trusted_signer,
        "separation_of_duties": bool(builder_att.fingerprint)
        and builder_att.fingerprint != release_att.fingerprint,
    }
    return FinalReleaseVerdict(
        checks=checks,
        builder_id=builder_id,
        builder_signer_fingerprint=builder_att.fingerprint,
        release_signer_fingerprint=release_att.fingerprint,
    )
