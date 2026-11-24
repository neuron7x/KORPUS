"""Live full-subject GitHub admission. There is deliberately no saved-receipt input."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from github_coverage_admission import verified_coverage
from github_evidence_artifact import admit_artifact, artifact_inventory
from github_evidence_result import CapturedArtifact, HostedEvidence, result
from github_evidence_run import (
    PACKAGE,
    POSTGRES,
    SECURITY,
    SQLITE,
    AdmittedRun,
    Producer,
    Selection,
    admit_run,
)
from github_evidence_source import capture_checkout
from github_evidence_transport import GitHubTransport, insist
from github_package_admission import package_producer
from github_security_admission import verified_security


def _extra_artifact(
    api: GitHubTransport, run: AdmittedRun, producer: Producer, inventory: list[dict[str, Any]]
) -> CapturedArtifact:
    selected = package_producer(run.checkout) if producer == PACKAGE else producer
    artifact = admit_artifact(api, run, selected, inventory)
    if producer == PACKAGE:
        insist(
            set(artifact.members) == set(selected.required_members),
            "canonical package artifact has missing or unexpected members",
        )
    return CapturedArtifact.from_admitted(artifact)


def fetch_evidence(root: Path, selected: Selection) -> HostedEvidence:
    return fetch_with_artifacts(root, selected, ())[0]


def fetch_with_artifacts(
    root: Path, selected: Selection, extra_producers: tuple[Producer, ...]
) -> tuple[HostedEvidence, tuple[CapturedArtifact, ...]]:
    producers = (SQLITE, POSTGRES, SECURITY, *extra_producers)
    insist(
        len({producer.job for producer in producers}) == len(producers)
        and len({producer.artifact_prefix for producer in producers}) == len(producers),
        "additional artifact producers must be distinct",
    )
    checkout = capture_checkout(root)
    api = GitHubTransport()
    run = admit_run(api, selected, checkout)
    inventory = artifact_inventory(api, run)
    sqlite = admit_artifact(api, run, SQLITE, inventory)
    postgres = admit_artifact(api, run, POSTGRES, inventory)
    security = admit_artifact(api, run, SECURITY, inventory)
    coverage = verified_coverage(run, sqlite, postgres)
    verified_security(run, security)
    extras = tuple(_extra_artifact(api, run, producer, inventory) for producer in extra_producers)
    insist(capture_checkout(root) == checkout, "source changed during hosted evidence admission")
    return result(run, coverage, (sqlite, postgres, security)), extras
