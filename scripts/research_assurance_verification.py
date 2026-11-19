"""One research-assurance predicate for committed and packaged source identities."""

from __future__ import annotations

from collections.abc import Mapping

from assurance_snapshot_contract import snapshot_contract_valid


def research_assurance_failures(
    assurance: Mapping[str, object],
    snapshot: Mapping[str, object],
    release: str,
    source_digest: str,
    evidence_failure: str | None,
    snapshot_complete: bool,
    source_label: str,
) -> list[str]:
    failures = ["assurance status is not PASS"] * (assurance.get("status") != "PASS")
    failures += [f"assurance source digest does not match {source_label}"] * (
        assurance.get("source_tree_sha256") != source_digest
    )
    if evidence_failure is not None:
        failures.append(evidence_failure)
    if snapshot.get("status") != "PASS" or snapshot.get("release") != release:
        failures.append("assurance snapshot release/status mismatch")
    failures += ["assurance snapshot limitations mismatch"] * (
        snapshot.get("limitations") != assurance.get("limitations", [])
    )
    if not snapshot_contract_valid(snapshot) or not snapshot_complete:
        failures.append("assurance snapshot record set/content mismatch")
    return failures
