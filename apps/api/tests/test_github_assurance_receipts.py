from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from korpus.application.github_assurance_receipts import (
    CANONICAL_OWNER_ID,
    CANONICAL_REPOSITORY,
    CANONICAL_REPOSITORY_ID,
    CANONICAL_WORKFLOW_ID,
    CANONICAL_WORKFLOW_PATH,
    admission_payload,
    admitted_file,
    new_receipt,
    receipt_bound,
    sha256_bytes,
)

ROOT = Path(__file__).resolve().parents[3]


def _identity() -> dict[str, object]:
    return {
        "repository": CANONICAL_REPOSITORY,
        "repository_id": CANONICAL_REPOSITORY_ID,
        "repository_owner_id": CANONICAL_OWNER_ID,
        "workflow_id": CANONICAL_WORKFLOW_ID,
        "workflow_path": CANONICAL_WORKFLOW_PATH,
        "run_id": 42,
        "run_attempt": 3,
        "commit_sha": "a" * 40,
    }


def test_foreign_repository_or_workflow_cannot_relabel_a_valid_receipt() -> None:
    payload = b"evidence"
    receipt = new_receipt(
        _identity(),
        kind="source-sbom",
        job="source-sbom",
        source_tree_sha256="b" * 64,
        artifacts={"source-sbom.cdx.json": payload},
        subjects={},
    )
    for field, poison in (("repository_id", 1), ("workflow_id", 2), ("run_attempt", 4)):
        foreign = {**_identity(), field: poison}
        assert not receipt_bound(
            receipt,
            identity=foreign,
            kind="source-sbom",
            job="source-sbom",
            source_tree_sha256="b" * 64,
            artifacts={"source-sbom.cdx.json": payload},
        )


def test_forged_secondary_cannot_turn_zero_of_two_into_two_of_two_under_old_receipt() -> None:
    receipt = new_receipt(
        _identity(),
        kind="coverage-sqlite",
        job="sqlite-coverage",
        source_tree_sha256="b" * 64,
        artifacts={"coverage.json": b'{"totals":{"covered_branches":0}}'},
        subjects={"declared_current": "b" * 64},
    )
    forged = b'{"totals":{"covered_branches":2}}'
    assert not receipt_bound(
        receipt,
        identity=_identity(),
        kind="coverage-sqlite",
        job="sqlite-coverage",
        source_tree_sha256="b" * 64,
        artifacts={"coverage.json": forged},
    )


def test_admission_binds_exact_downloaded_bytes_and_artifact_id() -> None:
    payload = b"canonical"
    admission = admission_payload(
        _identity(),
        {
            "source-sbom": {
                "artifact_id": 99,
                "files": {
                    "source-sbom.cdx.json": {
                        "sha256": sha256_bytes(payload),
                        "bytes": len(payload),
                    }
                },
            }
        },
    )
    assert admitted_file(
        admission,
        identity=_identity(),
        artifact="source-sbom",
        name="source-sbom.cdx.json",
        payload=payload,
    )
    assert not admitted_file(
        admission,
        identity=_identity(),
        artifact="source-sbom",
        name="source-sbom.cdx.json",
        payload=b"forged",
    )
    self_declared = {**admission, "provider": "github-actions"}
    assert not admitted_file(
        self_declared,
        identity=_identity(),
        artifact="source-sbom",
        name="source-sbom.cdx.json",
        payload=payload,
    )


def test_publisher_does_not_launder_raw_or_unadmitted_coverage(tmp_path: Path) -> None:
    script = ROOT / "scripts/publish_release_evidence.py"
    spec = importlib.util.spec_from_file_location("publish_release_evidence_test", script)
    assert spec is not None and spec.loader is not None
    publish = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publish)
    publish.ROOT = tmp_path
    raw = tmp_path / "var/coverage.json"
    raw.parent.mkdir(parents=True)
    raw.write_text(json.dumps({"totals": {"num_statements": 1, "num_branches": 1}}))
    assert publish.coverage_projection("c" * 64, "v0") is None

    imported = tmp_path / "var/ci-evidence"
    imported.mkdir()
    (imported / "coverage-union.json").write_text(raw.read_text())
    (imported / "coverage-gap-plan.json").write_text("{}")
    (imported / "coverage-ci-receipt.json").write_text("{}")
    (imported / "assurance-admission.json").write_text("{}")
    assert publish.coverage_projection("c" * 64, "v0") is None
