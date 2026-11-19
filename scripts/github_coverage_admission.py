"""Recompute both hosted coverage subjects from captured native data and actual source."""

from __future__ import annotations

import re
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from coverage_execution_contract import (
    DEFAULT_SOURCE,
    config_text,
    locked_version,
    native_report,
    semantic_report,
)
from coverage_receipt_contract import ReceiptSubject, verify_subject
from coverage_union import combine_native, same_subject, union_metadata
from github_evidence_artifact import AdmittedArtifact, digest
from github_evidence_run import POSTGRES, SQLITE, AdmittedRun, timestamp
from github_evidence_source import frozen_checkout
from github_evidence_transport import insist, strict_object


def execution_window(record: dict[str, Any], job: dict[str, Any]) -> None:
    insist(
        timestamp(job.get("started_at"))
        <= timestamp(record.get("started_at"))
        <= timestamp(record.get("completed_at"))
        < timestamp(job.get("completed_at")) + 1,
        "execution receipt is outside its authenticated producer job",
    )


def _version(root: Path) -> str:
    versions = re.findall(
        r"^coverage==([^\s\\]+)",
        (root / "apps/api/requirements.dev.lock").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    version = locked_version()
    insist(versions == [version], "checked-out coverage lock differs from the verifying toolchain")
    return version


def _dataset(
    dialect: str, artifact: AdmittedArtifact, run: AdmittedRun, temporary: Path, source_root: Path
) -> dict[str, Any]:
    prefix = "coverage-sqlite" if dialect == "sqlite" else "coverage-postgres"
    report_name = "coverage.json" if dialect == "sqlite" else prefix + ".json"
    data_bytes = artifact.members[prefix + ".data"]
    report_bytes = artifact.members[report_name]
    receipt_bytes = artifact.members[prefix + "-receipt.json"]
    record = strict_object(receipt_bytes, dialect + " coverage receipt")
    subject = ReceiptSubject(
        dialect=dialect,
        version=_version(source_root),
        source=run.checkout.source,
        sources=DEFAULT_SOURCE,
        configuration=config_text(DEFAULT_SOURCE),
        run=run.receipt_run,
        artifacts={
            "data": {"path": "var/" + prefix + ".data", "sha256": digest(data_bytes)},
            "report": {"path": "var/" + report_name, "sha256": digest(report_bytes)},
        },
    )
    verify_subject(record, subject)
    execution_window(record["execution"], artifact.job)
    saved_data = temporary / f"{dialect}.data"
    saved_data.write_bytes(data_bytes)
    (temporary / f"{dialect}-receipt.json").write_bytes(receipt_bytes)
    reported = strict_object(report_bytes, dialect + " coverage report")
    regenerated = native_report(
        saved_data, temporary / f"{dialect}.json", source_root, DEFAULT_SOURCE
    )
    insist(
        semantic_report(reported) == semantic_report(regenerated),
        f"{dialect} report does not describe its native dataset and actual source universe",
    )
    return regenerated


def verified_coverage(
    run: AdmittedRun, sqlite: AdmittedArtifact, postgres: AdmittedArtifact
) -> dict[str, Any]:
    insist(
        sqlite.producer == SQLITE and postgres.producer == POSTGRES, "coverage producer mismatch"
    )
    for name in POSTGRES.required_members:
        insist(
            name not in sqlite.members or sqlite.members[name] == postgres.members[name],
            "secondary coverage copy conflicts with its authoritative PostgreSQL artifact",
        )
    with (
        TemporaryDirectory(prefix="github-coverage-") as directory,
        frozen_checkout(run.checkout) as source_root,
    ):
        temporary = Path(directory)
        primary = _dataset("sqlite", sqlite, run, temporary, source_root)
        secondary = _dataset("postgresql", postgres, run, temporary, source_root)
        divergence = same_subject(primary, secondary)
        insist(divergence is None, "coverage subjects differ: " + str(divergence))
        merged = combine_native(source_root, list(DEFAULT_SOURCE), temporary)
        merged["dialect_union"] = union_metadata(run.checkout.source, temporary)
        published = strict_object(sqlite.members["coverage-union.json"], "producer coverage union")
        insist(
            semantic_report(published) == semantic_report(merged),
            "producer coverage union conflicts with independently combined native datasets",
        )
    return merged
