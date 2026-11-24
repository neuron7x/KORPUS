"""Immutable in-memory output of live admission; serialized diagnostics are not authority."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Any

from github_evidence_artifact import AdmittedArtifact
from github_evidence_run import POSTGRES, SECURITY, SQLITE, AdmittedRun
from github_evidence_transport import insist
from korpus.application.github_release_context import (
    CANONICAL_GITHUB_OWNER_ID,
    CANONICAL_GITHUB_REPOSITORY,
    CANONICAL_GITHUB_REPOSITORY_ID,
)


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")


@dataclass(frozen=True)
class HostedIdentity:
    repository: str
    repository_id: int
    owner_id: int
    workflow_id: int
    workflow_path: str
    ref: str
    head_sha: str
    checkout_commit_sha: str
    checkout_tree_oid: str
    run_id: int
    run_attempt: int
    evidence_source_sha256: str
    coverage_source_sha256: str
    tracked_tree_sha256: str
    tracked_tree_with_mode_sha256: str


@dataclass(frozen=True)
class CapturedArtifact:
    artifact_id: int
    name: str
    producer_job_id: int
    producer_job_name: str
    zip_sha256: str
    zip_bytes: bytes
    members: Mapping[str, bytes]
    receipt_bytes: bytes

    @classmethod
    def from_admitted(cls, artifact: AdmittedArtifact) -> CapturedArtifact:
        return cls(
            artifact.metadata["id"],
            artifact.metadata["name"],
            artifact.job["id"],
            artifact.producer.job,
            artifact.archive_sha256,
            artifact.archive_bytes,
            artifact.members,
            json_bytes(artifact.receipt),
        )


@dataclass(frozen=True)
class HostedEvidence:
    identity: HostedIdentity
    coverage_bytes: bytes
    artifacts: tuple[CapturedArtifact, ...]
    source_members: Mapping[str, bytes]
    source_identity_members: Mapping[str, bytes]

    @property
    def receipt(self) -> dict[str, Any]:
        jobs = {artifact.producer_job_name for artifact in self.artifacts}
        roles = {
            SQLITE.job: ("sqlite",),
            POSTGRES.job: ("postgresql",),
            SECURITY.job: ("source-sbom", "source-scanners"),
        }
        return {
            "schema": "korpus.github-evidence-admission.v1",
            "status": "PASS",
            "authority": "live GitHub HTTPS metadata, job upload logs and immutable artifact bytes",
            "identity": asdict(self.identity),
            "subjects": [
                subject for job, subjects in roles.items() if job in jobs for subject in subjects
            ],
            "artifacts": [json.loads(artifact.receipt_bytes) for artifact in self.artifacts],
            "production_authorized": False,
            "signature_verified": False,
        }

    def coverage_projection(self, release: str) -> dict[str, Any]:
        insist(
            {SQLITE.job, POSTGRES.job, SECURITY.job}
            <= {artifact.producer_job_name for artifact in self.artifacts},
            "coverage publication requires the complete coverage/SBOM/scanner subject",
        )
        totals = json.loads(self.coverage_bytes)["totals"]
        statements, branches = totals["num_statements"], totals["num_branches"]
        insist(statements > 0 and branches > 0, "coverage has no executable line/branch universe")
        return {
            "schema": "korpus.coverage-report.v1",
            "status": "PASS",
            "release": release,
            "source_tree_sha256": self.identity.evidence_source_sha256,
            "statement_coverage_percent": round(100 * totals["covered_lines"] / statements, 4),
            "branch_coverage_percent": round(100 * totals["covered_branches"] / branches, 4),
            "measured_from": "independent native combination of admitted GitHub artifact bytes",
            "github_evidence": self.receipt,
        }


def result(
    run: AdmittedRun, coverage: dict[str, Any], artifacts: tuple[AdmittedArtifact, ...]
) -> HostedEvidence:
    identity = HostedIdentity(
        CANONICAL_GITHUB_REPOSITORY,
        int(CANONICAL_GITHUB_REPOSITORY_ID),
        int(CANONICAL_GITHUB_OWNER_ID),
        run.metadata["workflow_id"],
        run.metadata["path"],
        run.selected.ref,
        run.metadata["head_sha"],
        run.checkout.commit,
        run.checkout.tree,
        run.selected.run_id,
        run.selected.attempt,
        run.checkout.evidence_digest,
        run.checkout.source["sha256"],
        run.checkout.tracked_tree_sha256,
        run.checkout.tracked_tree_with_mode_sha256,
    )
    return HostedEvidence(
        identity,
        json_bytes(coverage),
        tuple(CapturedArtifact.from_admitted(a) for a in artifacts),
        MappingProxyType(
            {
                path.as_posix(): content
                for path, _mode, content in (*run.checkout.files, *run.checkout.identity_files)
            }
        ),
        MappingProxyType(
            {path.as_posix(): content for path, _mode, content in run.checkout.identity_files}
        ),
    )
