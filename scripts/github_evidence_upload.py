"""Bind upload evidence within one invocation of the serial producer steps."""

from __future__ import annotations

import re
from typing import Any

from github_evidence_run import UPLOAD_ACTION, timestamp
from github_evidence_transport import insist

RUN_HEADER = "##[group]Run "


def _invocations(payload: bytes, upload: dict[str, Any]) -> list[list[str]]:
    start, end = timestamp(upload["started_at"]), timestamp(upload["completed_at"]) + 1
    invocations: list[list[str]] = []
    current: list[str] = []
    for line in payload.decode("utf-8").splitlines():
        instant, separator, message = line.partition(" ")
        # Endgroup closes runner metadata before the action runs. Every Run
        # header, including another action or shell step, starts a new invocation.
        if message.startswith(RUN_HEADER):
            current = []
            invocations.append(current)
        if (
            invocations
            and separator
            and re.fullmatch(r"\d{4}-\d\d-\d\dT\S+Z", instant)
            and start <= timestamp(instant) < end
        ):
            current.append(message)
    return invocations


def validate_upload_log(payload: bytes, record: dict[str, Any], upload: dict[str, Any]) -> None:
    expected = (
        RUN_HEADER + UPLOAD_ACTION,
        "SHA256 digest of uploaded artifact is " + record["digest"].removeprefix("sha256:"),
        f"Artifact {record['name']} successfully finalized. Artifact ID {record['id']}",
    )
    matches = [lines for lines in _invocations(payload, upload) if expected[2] in lines]
    insist(
        len(matches) == 1 and all(matches[0].count(message) == 1 for message in expected),
        "authenticated producer log does not bind the pinned upload action, artifact ID and digest",
    )
    lines = matches[0]
    insist(
        [lines.index(message) for message in expected] == sorted(lines.index(m) for m in expected),
        "producer upload log sequence is inconsistent",
    )
