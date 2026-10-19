from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from korpus.application.github_assurance_receipts import (
    admission_payload,
    admitted_file,
    canonical_identity,
    receipt_bound,
    sha256_bytes,
)
from korpus.application.provenance import compute_source_digest
from korpus.application.release_claim_hosted import (
    ARTIFACT_GROUP,
    ATTESTATION_SCHEMA,
    CLAIM_EXECUTORS,
    allowed_source_ref,
)
from korpus.application.release_claim_tree import tracked_tree_digest
from release_identity import release_tag

ATTESTATION_NAME = "RELEASE_CLAIM_ATTESTATION.json"
RECEIPT_NAME = "RELEASE_CLAIM_RECEIPT.json"
BUNDLE_NAME = "RELEASE_CLAIM_ATTESTATION.sigstore.json"
EXPECTED_FILES = frozenset({ATTESTATION_NAME, RECEIPT_NAME, BUNDLE_NAME})
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
Verifier = Callable[[Path, Path, Path, str, str], None]


def object_from_bytes(payload: bytes, name: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{name} is not valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{name} is not a JSON object")
    return value


def _expected_artifacts(root: Path, release: str) -> dict[str, set[str]]:
    merge = object_from_bytes(
        (root / "reports/regression/FULL_REGRESSION_CURRENT.json").read_bytes(),
        "canonical regression merge",
    )
    shards = merge.get("shards")
    if not isinstance(shards, int) or isinstance(shards, bool) or shards < 1:
        raise ValueError("canonical regression merge has no positive shard count")
    return {
        "CLM-REGRESSION": {
            f"reports/release/{release}/FULL_BACKEND_REPORT.json",
            "reports/regression/FULL_REGRESSION_CURRENT.json",
            *(f"reports/regression/shards/shard-{index}.json" for index in range(shards)),
            *(f"reports/regression/shards/shard-{index}.junit.xml" for index in range(shards)),
        },
        "CLM-WEB": {
            f"reports/release/{release}/WEB_REGRESSION_REPORT.json",
            f"reports/release/{release}/WEB_REGRESSION_REPORT.tap",
        },
        "CLM-MUTATION": {
            "reports/MUTATION_FULL_CATALOGUE_CURRENT.json",
            "reports/MUTATION_REPORT.json",
        },
        "CLM-INFERENCE-SECURITY": {
            f"reports/release/{release}/INFERENCE_SECURITY_GATE.json",
            f"reports/release/{release}/INFERENCE_SECURITY_GATE.junit.xml",
        },
    }


def _artifacts_bound(root: Path, declared: object, expected: set[str]) -> bool:
    if not isinstance(declared, Mapping) or set(declared) != expected:
        return False
    for relative, record in declared.items():
        path, target = PurePosixPath(str(relative)), root / str(relative)
        if path.is_absolute() or ".." in path.parts or not target.is_file():
            return False
        if not isinstance(record, Mapping):
            return False
        payload = target.read_bytes()
        valid = (
            set(record) == {"sha256", "bytes"}
            and record.get("sha256") == sha256_bytes(payload)
            and record.get("bytes") == len(payload)
        )
        if not valid:
            return False
    return True


def _identity_bound(
    attestation: Mapping[str, Any], release: str, source: str, tracked: str, source_ref: str
) -> bool:
    return (
        set(attestation)
        == {
            "schema",
            "status",
            "release",
            "source_tree_sha256",
            "digest_scope",
            "tracked_tree_sha256",
            "source_ref",
            "claims",
        }
        and attestation.get("schema") == ATTESTATION_SCHEMA
        and attestation.get("status") == "PASS"
        and attestation.get("release") == release
        and attestation.get("source_tree_sha256") == source
        and attestation.get("digest_scope") == "evidence_paths"
        and attestation.get("tracked_tree_sha256") == tracked
        and attestation.get("source_ref") == source_ref
    )


def _claims_bound(root: Path, claims: object, expected: Mapping[str, set[str]]) -> bool:
    if not isinstance(claims, Mapping) or set(claims) != set(CLAIM_EXECUTORS):
        return False
    for claim_id, executor in CLAIM_EXECUTORS.items():
        entry = claims[claim_id]
        valid = (
            isinstance(entry, Mapping)
            and set(entry) == {"status", "executor", "exit_code", "result", "artifacts"}
            and entry.get("status") == "PASS"
            and entry.get("executor") == executor
            and entry.get("exit_code") == 0
            and isinstance(entry.get("result"), Mapping)
            and _artifacts_bound(root, entry.get("artifacts"), expected[claim_id])
        )
        if not valid:
            raise ValueError(f"release-claim attestation entry is invalid: {claim_id}")
    return True


def _admission(
    identity: Mapping[str, Any], artifact_id: int, files: Mapping[str, bytes]
) -> dict[str, Any]:
    group = {
        ARTIFACT_GROUP: {
            "artifact_id": artifact_id,
            "files": {
                name: {"sha256": sha256_bytes(payload), "bytes": len(payload)}
                for name, payload in files.items()
            },
        }
    }
    admission = admission_payload(identity, group)
    admitted = all(
        admitted_file(
            admission, identity=identity, artifact=ARTIFACT_GROUP, name=name, payload=payload
        )
        for name, payload in files.items()
    )
    if not admitted:
        raise ValueError("release-claim artifact admission does not bind every downloaded byte")
    return {str(key): value for key, value in admission.items()}


def validate_downloaded(
    root: Path,
    identity: Mapping[str, Any],
    artifact_id: int,
    files: Mapping[str, bytes],
    source_ref: str,
    verifier: Verifier,
) -> dict[str, Any]:
    if not canonical_identity(identity) or set(files) != EXPECTED_FILES or artifact_id < 1:
        raise ValueError("run identity or release-claim artifact set is non-canonical")
    commit = identity.get("commit_sha")
    if not isinstance(commit, str) or _COMMIT.fullmatch(commit) is None:
        raise ValueError("canonical run has no exact commit")
    if not allowed_source_ref(source_ref):
        raise ValueError("canonical run has no allowed source ref")
    release, source, tracked = (
        release_tag(root),
        compute_source_digest(root),
        tracked_tree_digest(root),
    )
    if tracked is None:
        raise ValueError("canonical tracked source tree cannot be measured")
    attestation = object_from_bytes(files[ATTESTATION_NAME], ATTESTATION_NAME)
    receipt = object_from_bytes(files[RECEIPT_NAME], RECEIPT_NAME)
    if not _identity_bound(attestation, release, source, tracked, source_ref):
        raise ValueError("release-claim attestation identity is stale or malformed")
    if not _claims_bound(root, attestation.get("claims"), _expected_artifacts(root, release)):
        raise ValueError("release-claim attestation claim set is invalid")
    subject = {
        "release-claims": {
            "release": release,
            "source_tree_sha256": source,
            "digest_scope": "evidence_paths",
            "tracked_tree_sha256": tracked,
            "source_ref": source_ref,
            "claims": sorted(CLAIM_EXECUTORS),
        }
    }
    bound = receipt.get("subjects") == subject and receipt_bound(
        receipt,
        identity=identity,
        kind="release-claims",
        job="release-claims",
        source_tree_sha256=tracked,
        artifacts={ATTESTATION_NAME: files[ATTESTATION_NAME]},
    )
    if not bound:
        raise ValueError("release-claim receipt is not bound to the exact attestation")
    admission = _admission(identity, artifact_id, files)
    with tempfile.TemporaryDirectory(prefix="korpus-release-claim-") as temp:
        attestation_path, bundle_path = Path(temp) / ATTESTATION_NAME, Path(temp) / BUNDLE_NAME
        attestation_path.write_bytes(files[ATTESTATION_NAME])
        bundle_path.write_bytes(files[BUNDLE_NAME])
        verifier(root, attestation_path, bundle_path, commit, source_ref)
    return admission
