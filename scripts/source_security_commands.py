"""Fixed scanner invocations; caller-controlled flags cannot weaken scan scope."""

from __future__ import annotations

import os
from pathlib import Path

from scripts.source_security_contract import IMAGES
from scripts.source_security_gitleaks import gitleaks_arguments, gitleaks_environment
from scripts.source_security_lock import LOCK_PATHS


def _container(tool: str, source: Path, output: Path, temporary: Path) -> list[str]:
    return [
        "/usr/bin/docker",
        "--config",
        str(temporary / "docker-config"),
        "run",
        "--rm",
        "--pull=never",
        "--platform",
        "linux/amd64",
        "--network",
        "none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=256",
        "--memory=2g",
        "--cpus=2",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=256m",
        "--mount",
        f"type=bind,src={source},dst=/source,readonly",
        "--mount",
        f"type=bind,src={output},dst=/output",
        "--workdir",
        "/source",
        "--env",
        "SYFT_CHECK_FOR_APP_UPDATE=false",
        *gitleaks_environment(tool),
        IMAGES[tool],
    ]


def _audit_command(
    kind: str,
    source: Path,
    output: Path,
    temporary: Path,
    scanner_python: Path,
) -> list[str]:
    command = [
        str(scanner_python),
        "-I",
        "-m",
        "pip_audit",
        "--strict",
        "--disable-pip",
        "--no-deps",
        "--vulnerability-service",
        "pypi",
        "--cache-dir",
        str(temporary / f"pypi-{kind}"),
        "--progress-spinner",
        "off",
        "--format",
        "json",
        "--output",
        str(output / f"pip-audit-{kind}.json"),
        "-r",
        str(source / LOCK_PATHS["runtime"]),
    ]
    # pip-audit --disable-pip does not traverse nested -r directives. Audit
    # both files explicitly; native JSON must contain the complete union.
    if kind == "dev":
        command += ["-r", str(source / LOCK_PATHS["dev"])]
    return command


def scanner_commands(
    root: Path,
    source: Path,
    output: Path,
    temporary: Path,
    scanner_python: Path,
    commit: str,
) -> dict[str, list[str]]:
    commands = {
        "gitleaks": [
            *_container("gitleaks", root, output, temporary),
            *gitleaks_arguments(commit),
        ]
    }
    for kind in ("runtime", "dev"):
        commands[f"pip-audit:{kind}"] = _audit_command(
            kind, source, output, temporary, scanner_python
        )
    commands["trivy"] = [
        *_container("trivy", source, output, temporary),
        "config",
        "--skip-check-update",
        "--cache-dir",
        "/tmp/trivy-cache",
        "--exit-code",
        "1",
        "--severity",
        "HIGH,CRITICAL",
        "--include-non-failures",
        "--ignorefile",
        "/source/.trivyignore.yaml",
        "--format",
        "json",
        "--output",
        "/output/trivy.json",
        "/source",
    ]
    commands["syft"] = [
        *_container("syft", source, output, temporary),
        "dir:/source",
        "-o",
        "cyclonedx-json@1.6=/output/tree-sbom.cdx.json",
    ]
    return commands
