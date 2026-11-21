"""Build two exact stdlib diagnostic binaries without changing scanner trust."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts.bounded_process import run_bounded
from scripts.scanner_engine_artifact import _elf
from scripts.scanner_stdlib_identity import compiler_identity, digest, source_identity
from scripts.scanner_stdlib_pins import (
    BUILD_ARGUMENTS,
    GO_ARCHIVE_SHA256,
    GO_ARCHIVE_URL,
    GO_VERSION,
    PATCHES,
    SOURCE_COMMIT,
    SOURCE_TREE,
    SOURCE_URL,
)
from scripts.source_security_contract import require
from scripts.trusted_system_tools import git_executable


@dataclass
class BuildCommands:
    environment: dict[str, str]
    deadline: float
    executions: list[dict[str, Any]] = field(default_factory=list)

    def run(self, label: str, command: list[str], cwd: Path) -> str:
        remaining = min(240.0, self.deadline - time.monotonic())
        require(remaining > 0, "source-build deadline exhausted")
        started = time.monotonic()
        code, stdout, stderr, timed_out, termination = run_bounded(
            command, cwd=cwd, env=self.environment, timeout_seconds=remaining
        )
        output = (stdout + stderr).encode()
        self.executions.append(
            {
                "label": label,
                "command": command,
                "exit_code": code,
                "timed_out": timed_out,
                "termination": termination,
                "elapsed_seconds": time.monotonic() - started,
                "output_sha256": hashlib.sha256(output).hexdigest(),
                "output_bytes": len(output),
            }
        )
        require(code == 0 and not timed_out, "pinned source-build command failed")
        require(len(output) <= 4 * 1024 * 1024, "source-build output exceeds its bound")
        return stdout


def build_environment(compiler: Path, temporary: Path) -> dict[str, str]:
    return {
        "PATH": f"{compiler.parent}:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "TZ": "UTC",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GOENV": "off",
        "GOFLAGS": "",
        "GOTOOLCHAIN": "local",
        "GOOS": "linux",
        "GOARCH": "amd64",
        "CGO_ENABLED": "0",
        "GOMAXPROCS": "2",
        "GOMODCACHE": str(temporary / "go-mod-cache"),
        "GOCACHE": str(temporary / "go-build-cache"),
        "GOPROXY": "https://proxy.golang.org",
        "GOSUMDB": "sum.golang.org",
    }


def source_checkout(commands: BuildCommands, source: Path) -> list[str]:
    executable = git_executable()
    require(executable is not None, "trusted Git executable unavailable")
    assert executable is not None
    git = [executable, "-c", "core.hooksPath=/dev/null", "-c", "core.autocrlf=false"]
    source.mkdir(mode=0o700)
    commands.run("source-init", [*git, "init", "--quiet", "--object-format=sha1"], source)
    commands.run(
        "source-fetch",
        [*git, "fetch", "--quiet", "--depth=1", "--no-tags", SOURCE_URL, SOURCE_COMMIT],
        source,
    )
    commands.run(
        "source-checkout", [*git, "checkout", "--quiet", "--detach", SOURCE_COMMIT], source
    )
    identity = commands.run(
        "source-git-identity", [*git, "rev-parse", "HEAD", "HEAD^{tree}"], source
    )
    require(identity.splitlines() == [SOURCE_COMMIT, SOURCE_TREE], "upstream Git identity differs")
    return git


def apply_patch(
    root: Path, source: Path, stage: str, commands: BuildCommands, git: list[str]
) -> dict[str, str]:
    name, expected = PATCHES[stage]
    patch = root / "config/scanner-diagnostics" / name
    require(digest(patch) == expected, "diagnostic patch bytes differ")
    base = [*git, "apply", "--unidiff-zero", "--whitespace=error-all"]
    commands.run(stage + "-patch-check", [*base, "--check", str(patch)], source)
    commands.run(stage + "-patch-apply", [*base, str(patch)], source)
    return {"name": name, "sha256": expected}


def build_variant(
    source: Path, temporary: Path, stage: str, compiler: Path, commands: BuildCommands
) -> tuple[Path, dict[str, Any]]:
    before = source_identity(source, stage)
    listing = commands.run(
        stage + "-engine-source",
        [str(compiler), "list", "-mod=readonly", "-json", "./regexp"],
        source,
    )
    require(json.loads(listing).get("GoFiles") == ["stdlib_regex.go"], "non-stdlib engine selected")
    commands.run(
        stage + "-tests",
        [str(compiler), "test", "-mod=readonly", "./detect", "./detect/codec", "-count=1"],
        source,
    )
    directory = temporary / stage
    directory.mkdir(mode=0o700)
    binary = directory / "gitleaks"
    command = [str(compiler), *BUILD_ARGUMENTS, "-o", str(binary), "."]
    commands.run(stage + "-build", command, source)
    raw = binary.read_bytes()
    require(len(raw) <= 64 * 1024 * 1024, "diagnostic binary exceeds its size bound")
    _elf(raw)
    binary.chmod(0o500)
    require(source_identity(source, stage) == before, "source changed during its build")
    return binary, {
        "source_inventory": before,
        "build_arguments": command[1:],
        "engine_source": "regexp/stdlib_regex.go",
        "binary_sha256": digest(binary),
        "binary_bytes": len(raw),
    }


def build_pair(root: Path, temporary: Path, receipt: dict[str, Any]) -> dict[str, Path]:
    compiler, identity = compiler_identity()
    receipt.update(
        source_url=SOURCE_URL,
        source_commit=SOURCE_COMMIT,
        source_tree=SOURCE_TREE,
        compiler=identity,
        official_compiler_archive_url=GO_ARCHIVE_URL,
        official_compiler_archive_sha256=GO_ARCHIVE_SHA256,
        trusted_build_attestation=False,
    )
    commands = BuildCommands(build_environment(compiler, temporary), time.monotonic() + 600)
    receipt["build_executions"] = commands.executions
    version = commands.run("compiler-version", [str(compiler), "version"], temporary).strip()
    require(version == f"go version {GO_VERSION} linux/amd64", "compiler version differs")
    source = temporary / "upstream"
    git = source_checkout(commands, source)
    receipt["original_source_inventory"] = source_identity(source, "original")
    receipt["variants"], binaries = {}, {}
    for stage in ("control", "candidate"):
        patch = apply_patch(root, source, stage, commands, git)
        binaries[stage], built = build_variant(source, temporary, stage, compiler, commands)
        receipt["variants"][stage] = {"patch": patch, **built}
    require(compiler_identity()[1] == identity, "compiler changed during the paired build")
    return binaries
