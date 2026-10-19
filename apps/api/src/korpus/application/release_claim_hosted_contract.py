from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from korpus.application.github_assurance_receipts import admitted_file, receipt_bound
from korpus.application.release_claim_admission import canonical_paths_admitted
from korpus.application.release_claim_common import EvidenceContext, load_object
from korpus.application.release_claim_hosted import (
    ARTIFACT_GROUP,
    CLAIM_EXECUTORS,
    TRUSTED_ROOT_PATH,
    attestation_identity,
    hosted_paths,
    receipt_subject,
)
from korpus.application.release_claim_sigstore import VERIFIER_CONFIG_PATH, sigstore_verified
from korpus.application.release_claim_tree import tracked_tree_digest


def _record(root: Path, relative: str) -> dict[str, Any]:
    payload = (root / relative).read_bytes()
    from korpus.application.github_assurance_receipts import sha256_bytes

    return {"sha256": sha256_bytes(payload), "bytes": len(payload)}


def _records(root: Path, paths: Sequence[str]) -> dict[str, dict[str, Any]] | None:
    if not paths or len(paths) != len(set(paths)):
        return None
    try:
        return {path: _record(root, path) for path in sorted(paths)}
    except OSError:
        return None


def _payloads(
    context: EvidenceContext,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], tuple[str, str, str, str]] | None:
    paths = hosted_paths(context.release)
    attestation, receipt, admission = (
        load_object(context.root / relative) for relative in paths[:3]
    )
    if attestation is None or receipt is None or admission is None:
        return None
    return attestation, receipt, admission, paths


def _admitted_bytes(
    context: EvidenceContext,
    admission: dict[str, Any],
    paths: tuple[str, str, str, str],
) -> tuple[bytes, bytes] | None:
    attestation_path, receipt_path, _, bundle_path = paths
    try:
        attestation = (context.root / attestation_path).read_bytes()
        receipt = (context.root / receipt_path).read_bytes()
        bundle = (context.root / bundle_path).read_bytes()
    except OSError:
        return None
    pairs = ((attestation_path, attestation), (receipt_path, receipt), (bundle_path, bundle))
    if not all(
        admitted_file(
            admission,
            identity=admission,
            artifact=ARTIFACT_GROUP,
            name=Path(relative).name,
            payload=payload,
        )
        for relative, payload in pairs
    ):
        return None
    return attestation, receipt


def hosted_execution_admitted(
    context: EvidenceContext, artifacts: Sequence[str], result: Mapping[str, Any]
) -> bool:
    payloads = _payloads(context)
    tracked, records = tracked_tree_digest(context.root), _records(context.root, artifacts)
    if (
        context.claim_id not in CLAIM_EXECUTORS
        or payloads is None
        or tracked is None
        or records is None
    ):
        return False
    attestation, receipt, admission, paths = payloads
    admitted = _admitted_bytes(context, admission, paths)
    claims = attestation.get("claims")
    entry = claims.get(context.claim_id) if isinstance(claims, dict) else None
    if admitted is None or not isinstance(entry, dict):
        return False
    attestation_path, _, _, bundle_path = paths
    source_ref = attestation.get("source_ref")
    canonical = sorted({*artifacts, *paths, TRUSTED_ROOT_PATH, VERIFIER_CONFIG_PATH})
    return (
        canonical_paths_admitted(context.root, canonical)
        and attestation_identity(attestation, context.release, context.source_digest, tracked)
        and entry.get("result") == dict(result)
        and entry.get("artifacts") == records
        and receipt.get("subjects")
        == receipt_subject(context.release, context.source_digest, tracked, source_ref)
        and sigstore_verified(context.root, attestation_path, bundle_path, receipt, source_ref)
        and receipt_bound(
            receipt,
            identity=admission,
            kind="release-claims",
            job="release-claims",
            source_tree_sha256=tracked,
            artifacts={Path(attestation_path).name: admitted[0]},
        )
    )
