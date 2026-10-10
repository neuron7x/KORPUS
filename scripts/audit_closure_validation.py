"""One closure predicate shared by canonical and local evidence lanes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from korpus.application.evidence_registry import verify_closure_registry

LOCAL_STATUSES = frozenset({"CLOSED_LOCAL", "MITIGATED_LOCAL"})


@dataclass(frozen=True)
class ClosureClassification:
    closed: frozenset[str]
    mitigated: frozenset[str]
    external: frozenset[str]
    open_technical: frozenset[str]

    @property
    def all_ids(self) -> frozenset[str]:
        return self.closed | self.mitigated | self.external | self.open_technical

    def status_for(self, finding_id: str) -> str:
        memberships = [
            name
            for name, values in (
                ("CLOSED_LOCAL", self.closed),
                ("MITIGATED_LOCAL", self.mitigated),
                ("EXTERNAL_DEBT", self.external),
                ("OPEN_TECH_DEBT", self.open_technical),
            )
            if finding_id in values
        ]
        if len(memberships) != 1:
            raise RuntimeError(
                f"finding {finding_id} has invalid closure classification: {memberships}"
            )
        return memberships[0]


def validate_registry(
    root: Path,
    source: dict[str, Any],
    evidence: dict[str, list[str]],
    classification: ClosureClassification,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    findings = source["findings"]
    if not isinstance(findings, list):
        raise RuntimeError("closure source findings must be a list")
    source_ids = {item["id"] for item in findings}
    if source_ids != classification.all_ids:
        raise RuntimeError(
            f"closure map mismatch missing={sorted(source_ids - classification.all_ids)} "
            f"extra={sorted(classification.all_ids - source_ids)}"
        )
    statuses = {item["id"]: classification.status_for(item["id"]) for item in findings}
    unresolved = verify_closure_registry(root, evidence, statuses)
    if unresolved:
        raise RuntimeError(
            "the closure registry cites evidence that does not resolve:\n  "
            + "\n  ".join(unresolved)
        )
    missing = [
        finding
        for finding, status in statuses.items()
        if status in LOCAL_STATUSES and not evidence.get(finding)
    ]
    if missing:
        raise RuntimeError(f"local statuses lack evidence: {missing}")
    return findings, statuses
