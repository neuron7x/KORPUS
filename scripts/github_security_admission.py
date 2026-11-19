"""Admit the exact source SBOM and scanner subject from one authenticated job."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from github_coverage_admission import execution_window
from github_evidence_artifact import AdmittedArtifact, digest
from github_evidence_run import SECURITY, AdmittedRun, timestamp
from github_evidence_source import frozen_checkout
from github_evidence_transport import insist, object_records, strict_object
from source_security_contract import (
    EXECUTION_NAMES,
    OUTPUT_MEMBERS,
    expected_tools,
    validate_outputs,
)
from source_security_execution import execution_succeeded


def _executions(record: dict[str, Any], job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    executions = object_records(record.get("executions"), "invalid security executions")
    insist(len(executions) == len(EXECUTION_NAMES), "incomplete security executions")
    insist(
        all(isinstance(item, dict) and isinstance(item.get("tool"), str) for item in executions)
        and {item["tool"] for item in executions} == set(EXECUTION_NAMES),
        "duplicated or foreign security execution",
    )
    for execution in executions:
        insist(
            execution_succeeded(execution),
            "security scanner did not execute successfully",
        )
        command = execution.get("command")
        insist(
            isinstance(command, list)
            and bool(command)
            and all(isinstance(part, str) and bool(part) for part in command),
            "security execution command is missing or malformed",
        )
        execution_window(execution, job)
    return {execution["tool"]: execution for execution in executions}


def _native_timestamps(members: Mapping[str, bytes], executions: dict[str, dict[str, Any]]) -> None:
    values = {
        "syft": strict_object(members["tree-sbom.cdx.json"], "tree SBOM")["metadata"]["timestamp"],
        "trivy": strict_object(members["trivy.json"], "Trivy report")["CreatedAt"],
    }
    for tool, value in values.items():
        execution = executions[tool]
        insist(
            int(timestamp(execution["started_at"]))
            <= timestamp(value)
            < int(timestamp(execution["completed_at"])) + 1,
            f"{tool} report timestamp is outside its admitted execution",
        )


def verified_security(run: AdmittedRun, artifact: AdmittedArtifact) -> dict[str, Any]:
    outputs = frozenset(OUTPUT_MEMBERS)
    insist(artifact.producer == SECURITY, "security artifact producer mismatch")
    insist(
        set(artifact.members) == outputs | {"source-security-receipt.json"},
        "security artifact has missing or unexpected members",
    )
    record = strict_object(
        artifact.members["source-security-receipt.json"], "source security receipt"
    )
    insist(
        record.get("schema") == "korpus.source-security-execution.v1"
        and record.get("status") == "PASS"
        and record.get("production_authorized") is False,
        "source security execution did not pass",
    )
    insist(record.get("run") == run.receipt_run, "security execution run/attempt mismatch")
    insist(
        record.get("source_commit_sha") == run.checkout.commit
        and record.get("source_tree_oid") == run.checkout.tree,
        "security execution checkout commit/tree mismatch",
    )
    insist(
        record.get("source_before") == run.checkout.source
        and record.get("source_after_sha256") == run.checkout.source["sha256"],
        "security execution measured a different source snapshot",
    )
    executions = _executions(record, artifact.job)
    members = {name: artifact.members[name] for name in outputs}
    artifacts = {
        name: {"path": "var/source-security/" + name, "sha256": digest(payload)}
        for name, payload in sorted(members.items())
    }
    insist(
        record.get("artifacts") == artifacts, "security output does not match its execution receipt"
    )
    with frozen_checkout(run.checkout) as source_root:
        insist(
            record.get("tools") == expected_tools(source_root), "security tool identity mismatch"
        )
        validate_outputs(members, source_root)
    _native_timestamps(members, executions)
    return record
