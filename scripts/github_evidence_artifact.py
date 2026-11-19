"""Capture exact GitHub artifact bytes and bind them to the successful uploading job."""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from coverage_execution_contract import canonical_bytes
from github_evidence_run import (
    REPOSITORY_ID,
    UPLOAD_ACTION,
    AdmittedRun,
    Producer,
    exact_integer,
    producer_job,
    timestamp,
)
from github_evidence_transport import (
    MAX_ARCHIVE_BYTES,
    MAX_LOG_BYTES,
    GitHubEvidenceError,
    GitHubTransport,
    insist,
    object_record,
)
from github_evidence_upload import validate_upload_log as _upload_log
from zip_safety import safety_failures


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def archive_members(payload: bytes) -> Mapping[str, bytes]:
    insist(len(payload) <= MAX_ARCHIVE_BYTES, "artifact archive byte budget exceeded")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            failures = safety_failures(archive)
            insist(not failures, "unsafe GitHub artifact ZIP: " + "; ".join(failures))
            members = {
                entry.filename: archive.read(entry)
                for entry in archive.infolist()
                if not entry.is_dir()
            }
    except (OSError, RuntimeError, zipfile.BadZipFile) as error:
        raise GitHubEvidenceError("GitHub artifact ZIP could not be read") from error
    return MappingProxyType(members)


def _metadata(
    record: dict[str, Any], run: AdmittedRun, producer: Producer, upload: dict[str, Any]
) -> None:
    name = f"{producer.artifact_prefix}-{run.selected.attempt}"
    insist(record.get("name") == name, "artifact name does not bind the selected attempt")
    insist(record.get("expired") is False, "artifact has expired or lacks expiry metadata")
    size = record.get("size_in_bytes")
    insist(type(size) is int and 0 < size <= MAX_ARCHIVE_BYTES, "invalid artifact size")
    value = record.get("digest")
    insist(
        isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None,
        "artifact lacks an immutable SHA256 digest",
    )
    workflow = object_record(
        record.get("workflow_run"), "artifact workflow-run metadata is missing"
    )
    exact_integer(workflow.get("id"), run.selected.run_id, "artifact run ID")
    exact_integer(workflow.get("repository_id"), REPOSITORY_ID, "artifact repository ID")
    exact_integer(workflow.get("head_repository_id"), REPOSITORY_ID, "artifact head repository ID")
    insist(workflow.get("head_sha") == run.metadata["head_sha"], "artifact commit mismatch")
    insist(workflow.get("head_branch") == run.metadata["head_branch"], "artifact branch mismatch")
    created = timestamp(record.get("created_at"))
    insist(
        timestamp(upload.get("started_at")) <= created < timestamp(upload.get("completed_at")) + 1,
        "artifact was not created during its producer upload step",
    )
    insist(created >= timestamp(run.metadata.get("run_started_at")), "artifact predates attempt")


@dataclass(frozen=True)
class AdmittedArtifact:
    producer: Producer
    metadata_bytes: bytes
    job_bytes: bytes
    archive_sha256: str
    log_sha256: str
    archive_bytes: bytes
    members: Mapping[str, bytes]

    @property
    def metadata(self) -> dict[str, Any]:
        return dict(json.loads(self.metadata_bytes))

    @property
    def job(self) -> dict[str, Any]:
        return dict(json.loads(self.job_bytes))

    @property
    def receipt(self) -> dict[str, Any]:
        return {
            "id": self.metadata["id"],
            "name": self.metadata["name"],
            "zip_sha256": self.archive_sha256,
            "zip_bytes": self.metadata["size_in_bytes"],
            "producer_job_id": self.job["id"],
            "producer_job_name": self.producer.job,
            "producer_log_sha256": self.log_sha256,
            "upload_action": UPLOAD_ACTION,
            "members": {
                name: {"sha256": digest(payload), "bytes": len(payload)}
                for name, payload in sorted(self.members.items())
            },
        }


def artifact_inventory(api: GitHubTransport, run: AdmittedRun) -> list[dict[str, Any]]:
    records = api.collection(f"/actions/runs/{run.selected.run_id}/artifacts", "artifacts")
    ids = [record.get("id") for record in records]
    insist(
        all(type(value) is int and value > 0 for value in ids) and len(ids) == len(set(ids)),
        "artifact inventory has invalid or duplicate IDs",
    )
    return records


def admit_artifact(
    api: GitHubTransport, run: AdmittedRun, producer: Producer, inventory: list[dict[str, Any]]
) -> AdmittedArtifact:
    job, upload = producer_job(run, producer)
    name = f"{producer.artifact_prefix}-{run.selected.attempt}"
    matches = [record for record in inventory if record.get("name") == name]
    insist(len(matches) == 1, f"required artifact missing or duplicated: {name}")
    record = matches[0]
    artifact_id = record["id"]
    _metadata(record, run, producer, upload)
    logs = api.download(f"/actions/jobs/{job['id']}/logs", MAX_LOG_BYTES)
    _upload_log(logs, record, upload)
    payload = api.download(f"/actions/artifacts/{artifact_id}/zip", MAX_ARCHIVE_BYTES)
    insist(len(payload) == record["size_in_bytes"], "downloaded artifact size mismatch")
    checksum = digest(payload)
    insist("sha256:" + checksum == record["digest"], "downloaded artifact SHA256 mismatch")
    members = archive_members(payload)
    insist(set(producer.required_members) <= set(members), f"{name}: required members missing")
    return AdmittedArtifact(
        producer,
        canonical_bytes(record),
        canonical_bytes(job),
        checksum,
        digest(logs),
        payload,
        members,
    )
