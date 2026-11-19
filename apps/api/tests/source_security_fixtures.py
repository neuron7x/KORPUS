"""Neutral examples of the native report shapes, not hosted execution receipts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5


def execution_record(
    tool: str, command: list[str], started: str, completed: str, code: int | bool = 0
) -> dict[str, Any]:
    from scripts.source_security_container import owned_command
    from scripts.source_security_contract import IMAGES

    if tool in IMAGES and command[0] == "neutral-fixture":
        command = ["/usr/bin/docker", "--config", "/tmp/neutral/docker-config", "run", IMAGES[tool]]
    actual, owned = owned_command(tool, command)
    result: dict[str, Any] = {
        "tool": tool,
        "command": actual,
        "exit_code": code,
        "started_at": started,
        "completed_at": completed,
    }
    if owned:
        result["cleanup"] = {
            "name": owned.name,
            "owner": owned.owner,
            "container_id": "e" * 64,
            "status": "ABSENT",
            "confirmed_absent": True,
            "remove_exit_code": None,
        }
    return result


def write_locks(root: Path) -> None:
    folder = root / "apps/api"
    folder.mkdir(parents=True)
    (folder / "requirements.runtime.lock").write_text(
        "example-runtime==1.2.3 \\\n    --hash=sha256:" + "a" * 64 + "\n"
    )
    (folder / "requirements.dev.lock").write_text(
        "-r requirements.runtime.lock\nexample-check==4.5.6 \\\n    --hash=sha256:"
        + "b" * 64
        + "\n"
    )
    (folder / "requirements.scanners.lock").write_text(
        "pip-audit==2.10.1 \\\n    --hash=sha256:" + "c" * 64 + "\n"
    )


def output_values() -> dict[str, Any]:
    seed = "example-check==4.5.6\nexample-runtime==1.2.3"
    runtime = {"name": "example-runtime", "version": "1.2.3", "vulns": []}
    dev = {"name": "example-check", "version": "4.5.6", "vulns": []}
    return {
        "gitleaks.json": [],
        "pip-audit-runtime.json": {"dependencies": [runtime], "fixes": []},
        "pip-audit-dev.json": {"dependencies": [dict(runtime), dev], "fixes": []},
        "lock-sbom.cdx.json": {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "version": 1,
            "serialNumber": uuid5(NAMESPACE_URL, "korpus-lock-sbom:v1\n" + seed).urn,
            "metadata": {"component": {"type": "application", "name": "korpus-api"}},
            "components": [
                {
                    "type": "library",
                    "name": "example-check",
                    "version": "4.5.6",
                    "scope": "excluded",
                    "purl": "pkg:pypi/example-check@4.5.6",
                },
                {
                    "type": "library",
                    "name": "example-runtime",
                    "version": "1.2.3",
                    "scope": "required",
                    "purl": "pkg:pypi/example-runtime@1.2.3",
                },
            ],
        },
        "tree-sbom.cdx.json": {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "version": 1,
            "serialNumber": "urn:uuid:12345678-1234-4234-8234-123456789abc",
            "metadata": {
                "timestamp": "2026-11-19T00:00:01Z",
                "tools": {
                    "components": [
                        {
                            "type": "application",
                            "author": "anchore",
                            "name": "syft",
                            "version": "1.44.0",
                        }
                    ]
                },
                "component": {"type": "file", "name": "/source", "bom-ref": "neutral-source"},
            },
            "components": [
                {
                    "type": "file",
                    "name": "/source/apps/api/requirements.runtime.lock",
                    "bom-ref": "neutral-file",
                }
            ],
        },
        "trivy.json": {
            "SchemaVersion": 2,
            "Trivy": {"Version": "0.70.0"},
            "CreatedAt": "2026-11-19T00:00:01Z",
            "ArtifactName": "/source",
            "ArtifactType": "filesystem",
            "Results": [
                {
                    "Target": "Dockerfile",
                    "Class": "config",
                    "Type": "dockerfile",
                    "MisconfSummary": {"Successes": 1, "Failures": 0},
                    "Misconfigurations": [{"ID": "DS-0001", "Status": "PASS", "Severity": "HIGH"}],
                }
            ],
        },
    }


def output_bytes(values: dict[str, Any] | None = None) -> dict[str, bytes]:
    return {name: json.dumps(value).encode() for name, value in (values or output_values()).items()}
