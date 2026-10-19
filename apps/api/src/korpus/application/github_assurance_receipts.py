"""Fail-closed contracts for evidence produced by canonical GitHub Actions.

The JSON files validated here are receipts, not signatures.  Their authority comes
from the importer obtaining them from an exact GitHub run and writing an admission
record from the GitHub API.  Consumers consequently require all three things: the
payload bytes, their producer receipt, and the import admission that names those
exact bytes.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping
from typing import Any

CANONICAL_REPOSITORY = "neuron7x/KORPUS"
CANONICAL_REPOSITORY_ID = 1_332_311_807
CANONICAL_OWNER_ID = 206_596_321
CANONICAL_WORKFLOW_ID = 332_983_284
CANONICAL_WORKFLOW_PATH = ".github/workflows/assurance.yml"
DIGEST_SCOPE = "tracked_tree"
RECEIPT_SCHEMA = "korpus.github-assurance-receipt.v1"
ADMISSION_SCHEMA = "korpus.github-assurance-admission.v1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_IDENTITY_FIELDS = (
    "repository",
    "repository_id",
    "repository_owner_id",
    "workflow_id",
    "workflow_path",
    "run_id",
    "run_attempt",
    "commit_sha",
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_identity(identity: Mapping[str, Any]) -> bool:
    """Identity is canonical and fully specific, rather than merely self-labelled."""

    return (
        identity.get("repository") == CANONICAL_REPOSITORY
        and identity.get("repository_id") == CANONICAL_REPOSITORY_ID
        and identity.get("repository_owner_id") == CANONICAL_OWNER_ID
        and identity.get("workflow_id") == CANONICAL_WORKFLOW_ID
        and identity.get("workflow_path") == CANONICAL_WORKFLOW_PATH
        and _positive_int(identity.get("run_id"))
        and _positive_int(identity.get("run_attempt"))
        and isinstance(identity.get("commit_sha"), str)
        and _COMMIT.fullmatch(identity["commit_sha"]) is not None
    )


def identity_from_environment() -> dict[str, Any]:
    """Read the immutable Actions identity, refusing local/self-declared producers."""

    workflow_ref = os.environ.get("GITHUB_WORKFLOW_REF", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    prefix = f"{repository}/"
    path = workflow_ref.removeprefix(prefix).partition("@")[0]
    identity: dict[str, Any] = {
        "repository": repository,
        "repository_id": _environment_int("GITHUB_REPOSITORY_ID"),
        "repository_owner_id": _environment_int("GITHUB_REPOSITORY_OWNER_ID"),
        "workflow_id": _environment_int("KORPUS_GITHUB_WORKFLOW_ID"),
        "workflow_path": path,
        "run_id": _environment_int("GITHUB_RUN_ID"),
        "run_attempt": _environment_int("GITHUB_RUN_ATTEMPT"),
        "commit_sha": os.environ.get("GITHUB_SHA", ""),
    }
    if os.environ.get("GITHUB_ACTIONS") != "true" or not canonical_identity(identity):
        raise ValueError("not the canonical GitHub assurance workflow identity")
    return identity


def identity_from_run(run: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize trusted GitHub API run metadata into the receipt identity shape."""

    repository = run.get("repository")
    owner = repository.get("owner") if isinstance(repository, Mapping) else None
    return {
        "repository": repository.get("full_name") if isinstance(repository, Mapping) else None,
        "repository_id": repository.get("id") if isinstance(repository, Mapping) else None,
        "repository_owner_id": owner.get("id") if isinstance(owner, Mapping) else None,
        "workflow_id": run.get("workflow_id"),
        "workflow_path": run.get("path"),
        "run_id": run.get("id"),
        "run_attempt": run.get("run_attempt"),
        "commit_sha": run.get("head_sha"),
    }


def same_identity(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return canonical_identity(left) and all(
        left.get(key) == right.get(key) for key in _IDENTITY_FIELDS
    )


def new_receipt(
    identity: Mapping[str, Any],
    *,
    kind: str,
    job: str,
    source_tree_sha256: str,
    artifacts: Mapping[str, bytes],
    subjects: Mapping[str, Any],
) -> dict[str, Any]:
    if not canonical_identity(identity) or _SHA256.fullmatch(source_tree_sha256) is None:
        raise ValueError("invalid canonical receipt identity or source digest")
    return {
        "schema": RECEIPT_SCHEMA,
        "kind": kind,
        "provider": "github-actions",
        **{key: identity[key] for key in _IDENTITY_FIELDS},
        "job": job,
        "source_tree": {"digest_scope": DIGEST_SCOPE, "sha256": source_tree_sha256},
        "subjects": dict(subjects),
        "artifacts": {
            name: {"sha256": sha256_bytes(payload), "bytes": len(payload)}
            for name, payload in artifacts.items()
        },
    }


def receipt_bound(
    receipt: Mapping[str, Any],
    *,
    identity: Mapping[str, Any],
    kind: str,
    job: str,
    source_tree_sha256: str,
    artifacts: Mapping[str, bytes],
) -> bool:
    declared = receipt.get("artifacts")
    source = receipt.get("source_tree")
    return (
        receipt.get("schema") == RECEIPT_SCHEMA
        and receipt.get("kind") == kind
        and receipt.get("provider") == "github-actions"
        and receipt.get("job") == job
        and same_identity(receipt, identity)
        and isinstance(source, Mapping)
        and source.get("digest_scope") == DIGEST_SCOPE
        and source.get("sha256") == source_tree_sha256
        and isinstance(declared, Mapping)
        and set(declared) == set(artifacts)
        and all(
            _artifact_record(declared.get(name), payload) for name, payload in artifacts.items()
        )
    )


def admitted_file(
    admission: Mapping[str, Any],
    *,
    identity: Mapping[str, Any],
    artifact: str,
    name: str,
    payload: bytes,
) -> bool:
    """Require external run admission for the exact payload bytes being consumed."""

    groups = admission.get("artifacts")
    group = groups.get(artifact) if isinstance(groups, Mapping) else None
    files = group.get("files") if isinstance(group, Mapping) else None
    return (
        admission.get("schema") == ADMISSION_SCHEMA
        and admission.get("provider") == "github-api"
        and same_identity(admission, identity)
        and isinstance(group, Mapping)
        and _positive_int(group.get("artifact_id"))
        and isinstance(files, Mapping)
        and _artifact_record(files.get(name), payload)
    )


def admission_payload(identity: Mapping[str, Any], groups: Mapping[str, Any]) -> dict[str, Any]:
    if not canonical_identity(identity):
        raise ValueError("GitHub API returned a non-canonical assurance identity")
    return {
        "schema": ADMISSION_SCHEMA,
        "provider": "github-api",
        **{key: identity[key] for key in _IDENTITY_FIELDS},
        "artifacts": dict(groups),
    }


def _artifact_record(record: Any, payload: bytes) -> bool:
    return (
        isinstance(record, Mapping)
        and record.get("sha256") == sha256_bytes(payload)
        and record.get("bytes") == len(payload)
    )


def _environment_int(name: str) -> int | None:
    try:
        return int(os.environ.get(name, ""))
    except ValueError:
        return None


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
