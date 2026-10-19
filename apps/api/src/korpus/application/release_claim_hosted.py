from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from korpus.application.github_assurance_receipts import sha256_bytes
from korpus.application.release_claim_tree import tracked_tree_digest

ATTESTATION_SCHEMA = "korpus.release-claim-attestation.v1"
ARTIFACT_GROUP = "release-claim-evidence"
CLAIM_EXECUTORS = {
    "CLM-REGRESSION": "backend",
    "CLM-WEB": "web",
    "CLM-MUTATION": "mutation",
    "CLM-INFERENCE-SECURITY": "inference",
}
ENTRY_KEYS = {"status", "executor", "exit_code", "result", "artifacts"}
TRUSTED_ROOT_PATH = "config/assurance/github-attestation-trusted-root.jsonl"
TRUSTED_ROOT_SHA256 = "65ca537f6ed8a47fd0e560c421baa1f6c1efb8b25fc200d8c5c02c0e92eb2b9c"
SIGNER_WORKFLOW = "neuron7x/KORPUS/.github/workflows/assurance.yml"
SOURCE_REF = "refs/heads/main"
BOOTSTRAP_REF = "refs/heads/integration/canonical-convergence-20261019-v2"


def allowed_source_ref(value: object) -> bool:
    return isinstance(value, str) and value in {SOURCE_REF, BOOTSTRAP_REF}


def hosted_paths(release: str) -> tuple[str, str, str, str]:
    base = f"reports/release/{release}/hosted"
    return (
        f"{base}/RELEASE_CLAIM_ATTESTATION.json",
        f"{base}/RELEASE_CLAIM_RECEIPT.json",
        f"{base}/RELEASE_CLAIM_ADMISSION.json",
        f"{base}/RELEASE_CLAIM_ATTESTATION.sigstore.json",
    )


def _record(root: Path, relative: str) -> dict[str, Any]:
    path = root / relative
    payload = path.read_bytes()
    return {"sha256": sha256_bytes(payload), "bytes": len(payload)}


def _records(root: Path, paths: Sequence[str]) -> dict[str, dict[str, Any]] | None:
    if not paths or len(paths) != len(set(paths)):
        return None
    try:
        return {path: _record(root, path) for path in sorted(paths)}
    except OSError:
        return None


def new_attestation(
    root: Path,
    release: str,
    source_digest: str,
    executions: Mapping[str, Mapping[str, Any]],
    *,
    source_ref: str = SOURCE_REF,
) -> dict[str, Any]:
    """Build the deterministic payload later receipted by canonical GitHub Actions."""
    tracked = tracked_tree_digest(root)
    if (
        re.fullmatch(r"[0-9a-f]{64}", source_digest) is None
        or tracked is None
        or not allowed_source_ref(source_ref)
        or set(executions) != set(CLAIM_EXECUTORS)
    ):
        raise ValueError("release-claim attestation identity is incomplete")
    claims: dict[str, Any] = {}
    for claim_id, executor in CLAIM_EXECUTORS.items():
        raw = executions[claim_id]
        paths, result = raw.get("artifacts"), raw.get("result")
        records = _records(root, paths) if isinstance(paths, list) else None
        if raw.get("executor") != executor or raw.get("exit_code") != 0:
            raise ValueError(f"{claim_id} execution did not pass the canonical executor")
        if records is None or not isinstance(result, Mapping):
            raise ValueError(f"{claim_id} execution has incomplete artifacts or result")
        claims[claim_id] = {
            "status": "PASS",
            "executor": executor,
            "exit_code": 0,
            "result": dict(result),
            "artifacts": records,
        }
    return {
        "schema": ATTESTATION_SCHEMA,
        "status": "PASS",
        "release": release,
        "source_tree_sha256": source_digest,
        "digest_scope": "evidence_paths",
        "tracked_tree_sha256": tracked,
        "source_ref": source_ref,
        "claims": claims,
    }


def _entry_shape(claim_id: str, entry: object) -> bool:
    if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
        return False
    artifacts, result = entry.get("artifacts"), entry.get("result")
    return (
        entry.get("status") == "PASS"
        and entry.get("executor") == CLAIM_EXECUTORS[claim_id]
        and entry.get("exit_code") == 0
        and isinstance(result, dict)
        and isinstance(artifacts, dict)
        and bool(artifacts)
        and all(
            isinstance(path, str)
            and isinstance(record, dict)
            and set(record) == {"sha256", "bytes"}
            and isinstance(record.get("sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) is not None
            and isinstance(record.get("bytes"), int)
            and not isinstance(record.get("bytes"), bool)
            and record["bytes"] >= 0
            for path, record in artifacts.items()
        )
    )


def attestation_identity(
    payload: dict[str, Any], release: str, source_digest: str, tracked: str
) -> bool:
    claims = payload.get("claims")
    return (
        set(payload)
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
        and payload.get("schema") == ATTESTATION_SCHEMA
        and payload.get("status") == "PASS"
        and payload.get("release") == release
        and payload.get("source_tree_sha256") == source_digest
        and payload.get("digest_scope") == "evidence_paths"
        and payload.get("tracked_tree_sha256") == tracked
        and allowed_source_ref(payload.get("source_ref"))
        and isinstance(claims, dict)
        and set(claims) == set(CLAIM_EXECUTORS)
        and all(_entry_shape(claim_id, claims[claim_id]) for claim_id in CLAIM_EXECUTORS)
    )


def receipt_subject(
    release: str, source_digest: str, tracked: str, source_ref: object
) -> dict[str, Any]:
    return {
        "release-claims": {
            "release": release,
            "source_tree_sha256": source_digest,
            "digest_scope": "evidence_paths",
            "tracked_tree_sha256": tracked,
            "source_ref": source_ref,
            "claims": sorted(CLAIM_EXECUTORS),
        }
    }
