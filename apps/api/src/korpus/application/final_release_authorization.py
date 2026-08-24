from __future__ import annotations

import hashlib
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

from korpus.application.attested_evidence import verify_ed25519_attestation


STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE = "https://slsa.dev/provenance/v1"


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


def _builder_parts(statement: Mapping[str, Any]) -> tuple[str, Mapping[str, Any], Mapping[str, Any]]:
    predicate = statement.get("predicate")
    predicate = predicate if isinstance(predicate, Mapping) else {}
    definition = predicate.get("buildDefinition")
    definition = definition if isinstance(definition, Mapping) else {}
    run = predicate.get("runDetails")
    run = run if isinstance(run, Mapping) else {}
    builder = run.get("builder")
    builder = builder if isinstance(builder, Mapping) else {}
    return str(builder.get("id", "")), definition, run


def _subject_bound(statement: Mapping[str, Any], artifact_name: str, artifact_sha256: str) -> bool:
    subjects = statement.get("subject")
    if not isinstance(subjects, list) or len(subjects) != 1 or not isinstance(subjects[0], Mapping):
        return False
    digest = subjects[0].get("digest")
    return (
        subjects[0].get("name") == artifact_name
        and isinstance(digest, Mapping)
        and digest.get("sha256") == artifact_sha256
    )


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
    release: str,
    trusted_release_signers: Collection[str],
    trusted_builder_signers: Collection[str],
    trusted_builder_ids: Collection[str],
) -> FinalReleaseVerdict:
    artifact_sha = _sha(artifact_bytes)
    builder_id, build_definition, _ = _builder_parts(builder_statement)
    external = build_definition.get("externalParameters")
    external = external if isinstance(external, Mapping) else {}
    builder_att = verify_ed25519_attestation(
        builder_statement_bytes,
        manifest_name=builder_statement_name,
        release=release,
        attestation=builder_attestation,
        trusted_fingerprints=trusted_builder_signers,
    )
    release_att = verify_ed25519_attestation(
        release_manifest_bytes,
        manifest_name=release_manifest_name,
        release=release,
        attestation=release_attestation,
        trusted_fingerprints=trusted_release_signers,
    )
    checks = {
        "production_assurance_pass": production_assurance.get("status") == "PASS",
        "production_assurance_authorized": production_assurance.get("production_authorized") is True,
        "release_manifest_bound": (
            release_manifest.get("release") == release
            and release_manifest.get("artifact") == artifact_name
            and release_manifest.get("artifact_sha256") == artifact_sha
            and release_manifest.get("source_manifest_sha256") == _sha(source_manifest_bytes)
            and release_manifest.get("production_assurance_sha256") == _sha(production_assurance_bytes)
        ),
        "builder_statement_type": (
            builder_statement.get("_type") == STATEMENT_TYPE
            and builder_statement.get("predicateType") == PREDICATE_TYPE
        ),
        "builder_provenance_verified": (
            _subject_bound(builder_statement, artifact_name, artifact_sha)
            and external.get("release") == release
            and external.get("sourceManifestSha256") == _sha(source_manifest_bytes)
        ),
        "builder_trusted": bool(builder_id) and builder_id in set(trusted_builder_ids),
        "builder_attestation_verified": builder_att.cryptographically_valid,
        "builder_trusted_signer": builder_att.trusted_signer,
        "release_attestation_verified": release_att.cryptographically_valid,
        "release_trusted_signer": release_att.trusted_signer,
        "separation_of_duties": bool(builder_att.fingerprint) and builder_att.fingerprint != release_att.fingerprint,
    }
    return FinalReleaseVerdict(
        checks=checks,
        builder_id=builder_id,
        builder_signer_fingerprint=builder_att.fingerprint,
        release_signer_fingerprint=release_att.fingerprint,
    )
