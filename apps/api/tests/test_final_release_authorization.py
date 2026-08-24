from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from korpus.application.final_release_authorization import evaluate_final_release

RELEASE = "v-test"
ARTIFACT_NAME = "KORPUS_SYSTEM_v-test.zip"
RELEASE_MANIFEST_NAME = "KORPUS_SYSTEM_v-test.release-manifest.json"
BUILDER_STATEMENT_NAME = "KORPUS_SYSTEM_v-test.builder-provenance.json"


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _attestation(data: bytes, name: str, key: Ed25519PrivateKey) -> tuple[dict[str, Any], str]:
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    fingerprint = hashlib.sha256(public).hexdigest()
    return {
        "algorithm": "Ed25519",
        "release": RELEASE,
        "manifest": name,
        "manifest_sha256": hashlib.sha256(data).hexdigest(),
        "public_key_pem": public.decode(),
        "public_key_sha256": fingerprint,
        "signature_base64": base64.b64encode(key.sign(data)).decode(),
    }, fingerprint


def _fixture() -> dict[str, Any]:
    artifact = b"canonical-artifact"
    source_manifest = b"source-manifest"
    assurance = {"status": "PASS", "production_authorized": True}
    assurance_bytes = _json_bytes(assurance)
    release_manifest = {
        "release": RELEASE,
        "artifact": ARTIFACT_NAME,
        "artifact_sha256": hashlib.sha256(artifact).hexdigest(),
        "source_manifest_sha256": hashlib.sha256(source_manifest).hexdigest(),
        "production_assurance_sha256": hashlib.sha256(assurance_bytes).hexdigest(),
    }
    release_manifest_bytes = _json_bytes(release_manifest)
    builder_statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "predicateType": "https://slsa.dev/provenance/v1",
        "subject": [{"name": ARTIFACT_NAME, "digest": {"sha256": hashlib.sha256(artifact).hexdigest()}}],
        "predicate": {
            "buildDefinition": {"externalParameters": {"release": RELEASE, "sourceManifestSha256": hashlib.sha256(source_manifest).hexdigest()}},
            "runDetails": {"builder": {"id": "builder://trusted"}},
        },
    }
    builder_bytes = _json_bytes(builder_statement)
    builder_key, release_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    builder_att, builder_fp = _attestation(builder_bytes, BUILDER_STATEMENT_NAME, builder_key)
    release_att, release_fp = _attestation(release_manifest_bytes, RELEASE_MANIFEST_NAME, release_key)
    return locals()


def _evaluate(data: dict[str, Any], **overrides: Any):
    kwargs = {
        "artifact_name": ARTIFACT_NAME,
        "artifact_bytes": data["artifact"],
        "source_manifest_bytes": data["source_manifest"],
        "production_assurance_bytes": data["assurance_bytes"],
        "production_assurance": data["assurance"],
        "release_manifest_name": RELEASE_MANIFEST_NAME,
        "release_manifest_bytes": data["release_manifest_bytes"],
        "release_manifest": data["release_manifest"],
        "release_attestation": data["release_att"],
        "builder_statement_name": BUILDER_STATEMENT_NAME,
        "builder_statement_bytes": data["builder_bytes"],
        "builder_statement": data["builder_statement"],
        "builder_attestation": data["builder_att"],
        "release": RELEASE,
        "trusted_release_signers": {data["release_fp"]},
        "trusted_builder_signers": {data["builder_fp"]},
        "trusted_builder_ids": {"builder://trusted"},
    }
    kwargs.update(overrides)
    return evaluate_final_release(**kwargs)


def test_final_release_requires_bound_artifact_trusted_builder_and_distinct_release_signer() -> None:
    verdict = _evaluate(_fixture())
    assert verdict.authorized is True
    assert verdict.as_dict()["failures"] == []


def test_final_release_rejects_untrusted_builder_identity() -> None:
    data = _fixture()
    verdict = _evaluate(data, trusted_builder_ids=set())
    assert verdict.authorized is False
    assert verdict.checks["builder_trusted"] is False


def test_final_release_rejects_untrusted_release_signer() -> None:
    data = _fixture()
    verdict = _evaluate(data, trusted_release_signers=set())
    assert verdict.authorized is False
    assert verdict.checks["release_trusted_signer"] is False


def test_final_release_rejects_artifact_digest_substitution() -> None:
    data = _fixture()
    verdict = _evaluate(data, artifact_bytes=b"substituted")
    assert verdict.authorized is False
    assert verdict.checks["release_manifest_bound"] is False
    assert verdict.checks["builder_provenance_verified"] is False


def test_final_release_requires_upstream_production_authorization() -> None:
    data = _fixture()
    assurance = {"status": "PASS", "production_authorized": False}
    assurance_bytes = _json_bytes(assurance)
    verdict = _evaluate(data, production_assurance=assurance, production_assurance_bytes=assurance_bytes)
    assert verdict.authorized is False
    assert verdict.checks["production_assurance_authorized"] is False
