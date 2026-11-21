"""Reuse the authoritative sandbox; the alternate binary remains diagnostic only."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts.source_security_commands import scanner_commands
from scripts.source_security_container import cleanup_valid
from scripts.source_security_contract import IMAGES, require
from scripts.source_security_execution import execute, execution_succeeded
from scripts.trusted_system_tools import trusted_executable


def engine_command(
    source: Path,
    output: Path,
    temporary: Path,
    binary: Path | None,
    arguments: list[str],
) -> list[str]:
    original = scanner_commands(source, source, output, temporary, Path("/unused"), "0" * 40)[
        "gitleaks"
    ]
    image_index = original.index(IMAGES["gitleaks"])
    prefix = original[:image_index]
    if binary is not None:
        require(binary.name == "gitleaks" and binary.is_absolute(), "unexpected binary location")
        prefix += [
            "--mount",
            f"type=bind,src={binary.parent},dst=/diagnostic-bin,readonly",
            "--entrypoint",
            "/diagnostic-bin/gitleaks",
        ]
    return [*prefix, IMAGES["gitleaks"], *arguments]


@dataclass(frozen=True)
class EngineSandbox:
    source: Path
    output: Path
    temporary: Path
    binary: Path
    binary_sha256: str
    deadline: float
    executions: list[dict[str, Any]] = field(default_factory=list)

    def remaining(self) -> None:
        # A 240-second child plus the existing bounded ownership cleanup must fit.
        require(time.monotonic() + 300 < self.deadline, "diagnostic job budget exhausted")

    def verify_binary(self) -> None:
        require(
            not self.binary.is_symlink()
            and self.binary.is_file()
            and hashlib.sha256(self.binary.read_bytes()).hexdigest() == self.binary_sha256,
            "verified release binary changed during the diagnostic",
        )

    def pull_image(self) -> dict[str, Any]:
        self.remaining()
        docker = trusted_executable("/usr/bin/docker")
        require(docker is not None, "trusted Docker executable unavailable")
        command = [
            str(docker),
            "--config",
            str(self.temporary / "docker-config"),
            "pull",
            "--platform",
            "linux/amd64",
            IMAGES["gitleaks"],
        ]
        record: dict[str, Any] = execute("image:gitleaks", command, self.output, self.source)
        self.executions.append(record)
        require(execution_succeeded(record), "pinned diagnostic image could not be provisioned")
        return record

    def run(
        self,
        label: str,
        arguments: list[str],
        *,
        release: bool,
        source: Path | None = None,
    ) -> tuple[dict[str, Any], Path]:
        self.remaining()
        self.verify_binary()
        require(re.fullmatch(r"[a-z][a-z0-9-]{0,60}", label) is not None, "unsafe probe label")
        output = self.output / label
        output.mkdir(mode=0o700)
        command = engine_command(
            source or self.source,
            output,
            self.temporary,
            self.binary if release else None,
            arguments,
        )
        started = time.monotonic()
        record: dict[str, Any] = {
            "tool": "gitleaks",
            "command": command,
            "execution_state": "PENDING",
            "exit_code": None,
        }
        self.executions.append(record)
        record.update(execute("gitleaks", command, output, self.source))
        record["execution_state"] = "RETURNED"
        record["wall_seconds_including_owned_cleanup"] = time.monotonic() - started
        with (output / "execution.json").open("x") as stream:
            stream.write(json.dumps(record, indent=2) + "\n")
        require(cleanup_valid(record), "diagnostic container cleanup is unproven")
        require(record["exit_code"] != 127, "diagnostic native executable unavailable")
        return record, output
