from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from korpus.application.final_release_authorization import evaluate_final_release
from korpus.application.final_release_provenance import ReleaseBuildContext

from scripts.final_release_context import local_material_digests

RELEASE = "v-test"
ARTIFACT_NAME = "KORPUS_SYSTEM_v-test.zip"
RELEASE_MANIFEST_NAME = "KORPUS_SYSTEM_v-test.release-manifest.json"
BUILDER_STATEMENT_NAME = "KORPUS_SYSTEM_v-test.builder-provenance.json"
SOURCE_COMMIT = "a" * 40
GITHUB_RUN_ID = "123456789"
GITHUB_RUN_ATTEMPT = "2"
VERIFICATION_TIME = datetime(2026, 10, 19, 0, 1, tzinfo=UTC)
BUILDER_ID = "https://github.com/neuron7x/KORPUS/.github/workflows/release.yml@refs/tags/v-test"
MATERIALS = {
    f"file:///{relative}": hashlib.sha256(relative.encode()).hexdigest()
    for relative in (
        "SOURCE_MANIFEST.json",
        "apps/api/src/korpus/release.json",
        "apps/api/requirements.runtime.lock",
        "apps/api/requirements.dev.lock",
        "apps/web/package-lock.json",
        "apps/api/Dockerfile",
        "apps/web/Dockerfile",
    )
}
ROOT = Path(__file__).resolve().parents[3]


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _attestation(data: bytes, name: str, key: Ed25519PrivateKey) -> tuple[dict[str, Any], str]:
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
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
        "git_commit": SOURCE_COMMIT,
        "artifact": ARTIFACT_NAME,
        "artifact_sha256": hashlib.sha256(artifact).hexdigest(),
        "source_manifest_sha256": hashlib.sha256(source_manifest).hexdigest(),
        "production_assurance_sha256": hashlib.sha256(assurance_bytes).hexdigest(),
    }
    release_manifest_bytes = _json_bytes(release_manifest)
    builder_statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "predicateType": "https://slsa.dev/provenance/v1",
        "subject": [
            {"name": ARTIFACT_NAME, "digest": {"sha256": hashlib.sha256(artifact).hexdigest()}}
        ],
        "predicate": {
            "buildDefinition": {
                "buildType": "https://korpus.dev/buildtypes/canonical-release-zip/v1",
                "externalParameters": {
                    "release": RELEASE,
                    "sourceManifestSha256": hashlib.sha256(source_manifest).hexdigest(),
                    "sourceCommit": SOURCE_COMMIT,
                },
                "resolvedDependencies": [
                    {"uri": uri, "digest": {"sha256": digest}} for uri, digest in MATERIALS.items()
                ],
            },
            "runDetails": {
                "builder": {"id": BUILDER_ID},
                "metadata": {
                    "invocationId": (
                        "https://github.com/neuron7x/KORPUS/actions/runs/"
                        f"{GITHUB_RUN_ID}/attempts/{GITHUB_RUN_ATTEMPT}"
                    ),
                    "startedOn": "2026-10-19T00:00:00Z",
                    "finishedOn": "2026-10-19T00:01:00Z",
                },
            },
        },
    }
    builder_bytes = _json_bytes(builder_statement)
    builder_key, release_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    builder_att, builder_fp = _attestation(builder_bytes, BUILDER_STATEMENT_NAME, builder_key)
    release_att, release_fp = _attestation(
        release_manifest_bytes, RELEASE_MANIFEST_NAME, release_key
    )
    return locals()


def _resign_builder(data: dict[str, Any]) -> None:
    data["builder_bytes"] = _json_bytes(data["builder_statement"])
    data["builder_att"], data["builder_fp"] = _attestation(
        data["builder_bytes"], BUILDER_STATEMENT_NAME, data["builder_key"]
    )


def _resign_release(data: dict[str, Any]) -> None:
    data["release_manifest_bytes"] = _json_bytes(data["release_manifest"])
    data["release_att"], data["release_fp"] = _attestation(
        data["release_manifest_bytes"], RELEASE_MANIFEST_NAME, data["release_key"]
    )


def _evaluate(data: dict[str, Any], **overrides: Any):
    kwargs = {
        "artifact_name": ARTIFACT_NAME,
        "artifact_bytes": data["artifact"],
        "source_manifest_bytes": data["source_manifest"],
        "production_assurance_bytes": data["assurance_bytes"],
        "release_manifest_name": RELEASE_MANIFEST_NAME,
        "release_manifest_bytes": data["release_manifest_bytes"],
        "release_attestation": data["release_att"],
        "builder_statement_name": BUILDER_STATEMENT_NAME,
        "builder_statement_bytes": data["builder_bytes"],
        "builder_attestation": data["builder_att"],
        "build_context": ReleaseBuildContext(
            release=RELEASE,
            source_commit_sha=SOURCE_COMMIT,
            github_run_id=GITHUB_RUN_ID,
            github_run_attempt=GITHUB_RUN_ATTEMPT,
            expected_materials=MATERIALS,
            verification_time=VERIFICATION_TIME,
        ),
        "trusted_release_signers": {data["release_fp"]},
        "trusted_builder_signers": {data["builder_fp"]},
        "trusted_builder_ids": {BUILDER_ID},
    }
    kwargs.update(overrides)
    return evaluate_final_release(**kwargs)


def test_same_actor_with_two_distinct_keys_remains_blocked_from_production_authority() -> None:
    data = _fixture()
    assert data["builder_fp"] != data["release_fp"]
    verdict = _evaluate(data)
    payload = verdict.as_dict()
    assert verdict.candidate_checks_passed is True
    assert verdict.authorized is False
    assert payload["status"] == "BLOCKED"
    assert payload["candidate_checks_passed"] is True
    assert payload["production_authorized"] is False
    assert payload["authorization_blockers"] == [
        "github_hosted_artifact_receipt_pending",
        "completed_github_run_receipt_absent",
        "independent_actor_receipts_absent",
    ]
    assert payload["checks"]["key_separation"] is True


def test_final_release_rejects_untrusted_builder_identity() -> None:
    data = _fixture()
    verdict = _evaluate(data, trusted_builder_ids=set())
    assert verdict.candidate_checks_passed is False
    assert verdict.checks["builder_trusted"] is False


def test_final_release_rejects_untrusted_release_signer() -> None:
    data = _fixture()
    verdict = _evaluate(data, trusted_release_signers=set())
    assert verdict.candidate_checks_passed is False
    assert verdict.checks["release_trusted_signer"] is False


def test_final_release_rejects_artifact_digest_substitution() -> None:
    data = _fixture()
    verdict = _evaluate(data, artifact_bytes=b"substituted")
    assert verdict.candidate_checks_passed is False
    assert verdict.checks["release_manifest_bound"] is False
    assert verdict.checks["builder_provenance_verified"] is False


def test_final_release_requires_upstream_production_authorization() -> None:
    data = _fixture()
    assurance = {"status": "PASS", "production_authorized": False}
    assurance_bytes = _json_bytes(assurance)
    verdict = _evaluate(data, production_assurance_bytes=assurance_bytes)
    assert verdict.candidate_checks_passed is False
    assert verdict.checks["production_assurance_authorized"] is False


def test_final_release_rejects_release_manifest_without_exact_source_commit() -> None:
    data = _fixture()
    data["release_manifest"].pop("git_commit")
    _resign_release(data)
    verdict = _evaluate(data)
    assert verdict.candidate_checks_passed is False
    assert verdict.checks["release_manifest_git_commit"] is False


def test_final_release_rejects_wrong_build_type_and_source_commit() -> None:
    data = _fixture()
    definition = data["builder_statement"]["predicate"]["buildDefinition"]
    definition["buildType"] = "https://attacker.invalid/build"
    definition["externalParameters"]["sourceCommit"] = "b" * 40
    _resign_builder(data)
    verdict = _evaluate(data)
    assert verdict.candidate_checks_passed is False
    assert verdict.checks["builder_build_type"] is False
    assert verdict.checks["builder_source_commit"] is False


def test_final_release_rejects_missing_or_substituted_resolved_material() -> None:
    data = _fixture()
    dependencies = data["builder_statement"]["predicate"]["buildDefinition"]["resolvedDependencies"]
    dependencies[0]["digest"]["sha256"] = "0" * 64
    _resign_builder(data)
    verdict = _evaluate(data)
    assert verdict.candidate_checks_passed is False
    assert verdict.checks["builder_materials_bound"] is False


def test_final_release_rejects_wrong_github_run_invocation() -> None:
    data = _fixture()
    metadata = data["builder_statement"]["predicate"]["runDetails"]["metadata"]
    metadata["invocationId"] = "https://github.com/attacker/KORPUS/actions/runs/1/attempts/1"
    _resign_builder(data)
    verdict = _evaluate(data)
    assert verdict.candidate_checks_passed is False
    assert verdict.checks["builder_invocation_bound"] is False


def test_final_release_rejects_missing_or_reversed_timestamps() -> None:
    data = _fixture()
    metadata = data["builder_statement"]["predicate"]["runDetails"]["metadata"]
    metadata["startedOn"] = "2026-10-19T00:02:00Z"
    metadata["finishedOn"] = "2026-10-19T00:01:00Z"
    _resign_builder(data)
    verdict = _evaluate(data)
    assert verdict.candidate_checks_passed is False
    assert verdict.checks["builder_timestamps_valid"] is False


def test_final_release_rejects_timestamps_outside_the_current_github_run_window() -> None:
    data = _fixture()
    metadata = data["builder_statement"]["predicate"]["runDetails"]["metadata"]
    metadata["startedOn"] = "2000-01-01T00:00:00Z"
    metadata["finishedOn"] = "2000-01-01T00:01:00Z"
    _resign_builder(data)
    verdict = _evaluate(data)
    assert verdict.candidate_checks_passed is False
    assert verdict.checks["builder_timestamps_valid"] is False


def test_final_release_rejects_attacker_workflow_even_when_explicitly_trusted() -> None:
    data = _fixture()
    attacker = "https://github.com/neuron7x/KORPUS/.github/workflows/attacker.yml@refs/tags/v-test"
    data["builder_statement"]["predicate"]["runDetails"]["builder"]["id"] = attacker
    _resign_builder(data)
    verdict = _evaluate(data, trusted_builder_ids={attacker})
    assert verdict.candidate_checks_passed is False
    assert verdict.checks["builder_trusted"] is False


def test_signed_unrelated_bytes_cannot_borrow_canonical_mapping_semantics() -> None:
    data = _fixture()
    data["builder_bytes"] = _json_bytes({"signed": "unrelated"})
    data["builder_att"], data["builder_fp"] = _attestation(
        data["builder_bytes"], BUILDER_STATEMENT_NAME, data["builder_key"]
    )
    verdict = _evaluate(data)
    assert verdict.candidate_checks_passed is False
    assert verdict.checks["builder_statement_type"] is False
    assert verdict.checks["builder_provenance_verified"] is False


def test_signed_json_with_duplicate_keys_is_refused() -> None:
    data = _fixture()
    data["release_manifest_bytes"] = b'{"release":"v-test","release":"attacker"}\n'
    data["release_att"], data["release_fp"] = _attestation(
        data["release_manifest_bytes"], RELEASE_MANIFEST_NAME, data["release_key"]
    )
    with pytest.raises(ValueError, match="duplicate key"):
        _evaluate(data)


def test_expected_materials_are_recomputed_from_local_files() -> None:
    actual = local_material_digests(ROOT)
    assert set(actual) == set(MATERIALS)
    for uri, digest in actual.items():
        relative = uri.removeprefix("file:///")
        assert digest == hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "malformed",
    [
        None,
        7,
        {"uri": "file:///x"},
        {"uri": 2, "digest": {"sha256": "0" * 64}},
        {"uri": "file:///x", "digest": {"other": "0" * 64}},
    ],
)
def test_release_material_refuses_invalid_dependency_shapes(malformed: object) -> None:
    from korpus.application.final_release_provenance import _material_entry

    assert _material_entry(malformed) is None


def test_release_materials_refuse_missing_invalid_and_malformed_inputs() -> None:
    from korpus.application.final_release_provenance import (
        REQUIRED_BUILD_MATERIALS,
        _resolved_materials_bound,
    )

    expected = {
        f"file:///{relative}": hashlib.sha256(relative.encode()).hexdigest()
        for relative in REQUIRED_BUILD_MATERIALS
    }
    dependencies = []
    for uri, digest in expected.items():
        dependencies.append({"uri": uri, "digest": {"sha256": digest}})
    valid = {"resolvedDependencies": dependencies}
    assert _resolved_materials_bound(valid, expected)

    incomplete = dict(expected)
    incomplete.pop(next(iter(incomplete)))
    assert not _resolved_materials_bound(valid, incomplete)

    invalid_digest = dict(expected)
    invalid_digest[next(iter(invalid_digest))] = "invalid-digest"
    assert not _resolved_materials_bound(valid, invalid_digest)

    malformed = list(valid["resolvedDependencies"])
    malformed[0] = {"uri": "file:///x", "digest": {"sha256": "0" * 64}, "extra": True}
    assert not _resolved_materials_bound({"resolvedDependencies": malformed}, expected)


def test_release_timestamp_refuses_missing_unzoned_and_nonstring_values() -> None:
    from korpus.application.final_release_provenance import _timestamp, _timestamps_bound

    assert _timestamp(None) is None
    assert _timestamp(123) is None
    assert _timestamp("not-a-date") is None
    assert _timestamp("2026-10-19T00:00:00") is None
    assert not _timestamps_bound(
        {"metadata": {"startedOn": None, "finishedOn": "2026-10-19T00:01:00Z"}},
        datetime(2026, 10, 19, 0, 1, tzinfo=UTC),
    )


@pytest.mark.parametrize("payload", [b"[]", b"null", b'""', b"5"])
def test_signed_evidence_refuses_nonobject_json(payload: bytes) -> None:
    from korpus.application.final_release_evidence import strict_signed_json_object

    with pytest.raises(ValueError, match="must contain an object"):
        strict_signed_json_object(payload, "release evidence")


def test_github_release_context_refuses_gitlab_and_invalid_commit() -> None:
    from korpus.application.github_release_context import (
        expected_github_release_environment,
        github_release_context_mismatches,
    )

    canonical = expected_github_release_environment("v-test")
    canonical["GITHUB_SHA"] = "a" * 40
    assert github_release_context_mismatches(canonical, "v-test") == []
    gitlab = {**canonical, "GITLAB_CI": "true"}
    assert github_release_context_mismatches(gitlab, "v-test") == ["GITLAB_CI"]
    invalid_sha = {**canonical, "GITHUB_SHA": "invalid"}
    assert github_release_context_mismatches(invalid_sha, "v-test") == ["GITHUB_SHA"]
    combined = {**gitlab, "GITHUB_SHA": "invalid"}
    assert github_release_context_mismatches(combined, "v-test") == [
        "GITHUB_SHA",
        "GITLAB_CI",
    ]


@pytest.mark.parametrize(
    ("field", "spoofed"),
    [
        ("GITHUB_REPOSITORY_ID", "1332311808"),
        ("GITHUB_REPOSITORY_OWNER_ID", "206596322"),
        ("GITHUB_REF_PROTECTED", "false"),
        ("RUNNER_ENVIRONMENT", "self-hosted"),
        (
            "GITHUB_WORKFLOW_REF",
            "neuron7x/KORPUS/.github/workflows/attacker.yml@refs/tags/v-test",
        ),
    ],
)
def test_release_context_refuses_spoofed_hosted_authority(field: str, spoofed: str) -> None:
    from korpus.application.github_release_context import (
        expected_github_release_environment,
        github_release_context_mismatches,
    )

    environment = expected_github_release_environment("v-test")
    environment["GITHUB_SHA"] = "a" * 40
    environment[field] = spoofed
    assert github_release_context_mismatches(environment, "v-test") == [field]


@pytest.mark.parametrize(
    ("field", "payload"),
    [
        ("assurance_bytes", b'{"status":"PASS","status":"FAIL"}\n'),
        ("builder_bytes", b'{"_type":"trusted","_type":"attacker"}\n'),
    ],
)
def test_duplicate_keys_in_other_signed_evidence_are_refused(field: str, payload: bytes) -> None:
    fixture = _fixture()
    fixture[field] = payload
    with pytest.raises(ValueError, match="duplicate key"):
        _evaluate(fixture)
