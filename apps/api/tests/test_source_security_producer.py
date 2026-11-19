from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import run_source_security as producer  # noqa: E402
from scripts import source_security_source as source  # noqa: E402
from scripts.source_security_commands import scanner_commands  # noqa: E402
from scripts.source_security_contract import EXECUTION_NAMES, IMAGES  # noqa: E402

from .source_security_fixtures import output_bytes, write_locks  # noqa: E402


@pytest.fixture
def prepared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict[str, Any]]:
    root = tmp_path / "repository"
    write_locks(root)
    (root / "neutral.txt").write_text("neutral source\n")
    files = [
        (path.relative_to(root), "0644", path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]
    temporary = tmp_path / "runner-temp"
    temporary.mkdir()
    monkeypatch.setenv("RUNNER_TEMP", str(temporary))
    identity = {
        "kind": "github-actions",
        "GITHUB_REPOSITORY": "example/repository",
        "GITHUB_SHA": "a" * 40,
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "2",
    }
    state: dict[str, Any] = {
        "calls": [],
        "exit_code": 0,
        "poison": "",
        "checkout": "a" * 40,
        "provision_calls": [],
        "provision_code": 0,
    }
    monkeypatch.setattr(source, "SOURCE_INPUTS", ("apps/api", "neutral.txt"))
    monkeypatch.setattr(producer, "SOURCE_INPUTS", ("apps/api", "neutral.txt"))
    monkeypatch.setattr(source, "run_identity", lambda: dict(identity))
    monkeypatch.setattr(source, "checkout_identity", lambda _root: (state["checkout"], "b" * 40))
    monkeypatch.setattr(source, "git_files", lambda _root: list(files))
    monkeypatch.setattr(producer, "trusted_executable", lambda path: path)
    monkeypatch.setattr(producer, "verify_scanner_python", lambda _path, _root: None)

    def execute(tool: str, command: list[str], output: Path, cwd: Path) -> dict[str, Any]:
        if tool.startswith("image:"):
            state["provision_calls"].append(command)
            return {
                "tool": tool,
                "command": command,
                "exit_code": state["provision_code"],
                "started_at": "2026-11-19T00:00:00Z",
                "completed_at": "2026-11-19T00:00:02Z",
            }
        state["calls"].append(tool)
        native = {
            "gitleaks": "gitleaks.json",
            "pip-audit:runtime": "pip-audit-runtime.json",
            "pip-audit:dev": "pip-audit-dev.json",
            "trivy": "trivy.json",
            "syft": "tree-sbom.cdx.json",
        }[tool]
        (output / native).write_bytes(output_bytes()[native])
        if tool == "syft":
            poison = state["poison"]
            if poison == "checkout":
                state["checkout"] = "c" * 40
            elif poison == "source":
                (root / "neutral.txt").write_text("changed source\n")
            elif poison == "frozen":
                (cwd / "neutral.txt").write_text("changed frozen source\n")
            elif poison == "missing":
                (output / "gitleaks.json").unlink()
            elif poison == "finding":
                (output / "gitleaks.json").write_text('[{"Secret":"REDACTED"}]')
        return {
            "tool": tool,
            "command": command,
            "exit_code": state["exit_code"] if tool == "gitleaks" else 0,
            "started_at": "2026-11-19T00:00:00Z",
            "completed_at": "2026-11-19T00:00:02Z",
        }

    monkeypatch.setattr(producer, "execute", execute)
    return root, state


def test_complete_fixture_execution_is_bound_and_only_writes_generated_paths(
    prepared: tuple[Path, dict[str, Any]],
) -> None:
    root, state = prepared
    before = {
        path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }
    receipt = producer.produce(root, Path("/external/scanner/python"))
    assert receipt["status"] == "PASS"
    assert receipt["production_authorized"] is False
    assert state["calls"] == list(EXECUTION_NAMES)
    assert len(receipt["provisioning"]) == 3
    assert [command[-1] for command in state["provision_calls"]] == list(IMAGES.values())
    for command in state["provision_calls"]:
        assert command[3:-1] == ["pull", "--platform", "linux/amd64"]
    assert receipt["source_commit_sha"] == "a" * 40
    assert receipt["source_tree_oid"] == "b" * 40
    assert receipt["source_after_sha256"] == receipt["source_before"]["sha256"]
    assert len(receipt["artifacts"]) == 6
    assert (
        json.loads((root / "var/source-security/source-security-receipt.json").read_bytes())
        == receipt
    )
    for path in root.rglob("*"):
        if path.is_file() and not path.is_relative_to(root / "var"):
            assert before[path.relative_to(root)] == path.read_bytes()


@pytest.mark.parametrize("code", [1, 124, 127, False])
def test_failed_provisioning_stops_before_native_execution(
    prepared: tuple[Path, dict[str, Any]], code: int | bool
) -> None:
    root, state = prepared
    state["provision_code"] = code
    receipt = producer.produce(root, Path("/external/scanner/python"))
    assert receipt["status"] == "FAIL"
    assert state["calls"] == []
    assert len(state["provision_calls"]) == 3
    assert all(item["exit_code"] == code for item in receipt["provisioning"])
    assert "image provisioning did not succeed" in receipt["error"]


@pytest.mark.parametrize("code", [1, 124, 127, False])
def test_failed_or_noninteger_execution_cannot_be_pass_with_clean_outputs(
    prepared: tuple[Path, dict[str, Any]], code: int | bool
) -> None:
    root, state = prepared
    state["exit_code"] = code
    receipt = producer.produce(root, Path("/external/scanner/python"))
    assert receipt["status"] == "FAIL"
    assert state["calls"] == list(EXECUTION_NAMES)
    assert receipt["executions"][0]["exit_code"] == code


@pytest.mark.parametrize("poison", ["checkout", "source", "frozen", "missing", "finding"])
def test_source_change_missing_output_or_native_finding_refuses_pass(
    prepared: tuple[Path, dict[str, Any]], poison: str
) -> None:
    root, state = prepared
    state["poison"] = poison
    receipt = producer.produce(root, Path("/external/scanner/python"))
    assert receipt["status"] == "FAIL"
    assert state["calls"] == list(EXECUTION_NAMES)
    assert receipt["error"]


def test_stale_output_directory_cannot_be_reused(prepared: tuple[Path, dict[str, Any]]) -> None:
    root, state = prepared
    producer.produce(root, Path("/external/scanner/python"))
    state["calls"] = []
    with pytest.raises(FileExistsError):
        producer.produce(root, Path("/external/scanner/python"))
    assert state["calls"] == []


def test_unverified_git_inventory_cannot_reach_scanners(
    prepared: tuple[Path, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, state = prepared
    monkeypatch.setattr(source, "git_files", lambda _root: None)
    receipt = producer.produce(root, Path("/external/scanner/python"))
    assert receipt["status"] == "FAIL"
    assert state["calls"] == []


def test_local_identity_cannot_be_upgraded_to_hosted_execution(
    prepared: tuple[Path, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, state = prepared
    monkeypatch.setattr(source, "run_identity", lambda: {"kind": "local"})
    assert producer.produce(root, Path("/external/scanner/python"))["status"] == "FAIL"
    assert state["calls"] == []


def test_fixed_scanner_commands_preserve_source_history_lock_and_policy_scope(
    tmp_path: Path,
) -> None:
    root, frozen, out, temp = (tmp_path / name for name in ("root", "frozen", "out", "temp"))
    commands = scanner_commands(root, frozen, out, temp, Path("/scanner/python"), "a" * 40)
    assert list(commands) == list(EXECUTION_NAMES)
    for tool in ("gitleaks", "trivy", "syft"):
        assert IMAGES[tool] in commands[tool]
        assert "--network" in commands[tool] and "none" in commands[tool]
        assert "--pull=never" in commands[tool]
    assert f"type=bind,src={root},dst=/source,readonly" in commands["gitleaks"]
    assert commands["gitleaks"][commands["gitleaks"].index("--log-opts") + 1] == "a" * 40
    for tool in ("trivy", "syft"):
        assert f"type=bind,src={frozen},dst=/source,readonly" in commands[tool]
    assert commands["pip-audit:runtime"].count("-r") == 1
    assert commands["pip-audit:dev"].count("-r") == 2
    assert str(frozen / "apps/api/requirements.runtime.lock") in commands["pip-audit:dev"]
    assert str(frozen / "apps/api/requirements.dev.lock") in commands["pip-audit:dev"]
    assert "--ignore-vuln" not in commands["pip-audit:dev"]
    assert "HIGH,CRITICAL" in commands["trivy"]
    assert "/source/.trivyignore.yaml" in commands["trivy"]
    assert "--include-non-failures" in commands["trivy"]
    assert "--skip-check-update" in commands["trivy"]
    assert "cyclonedx-json@1.6=/output/tree-sbom.cdx.json" in commands["syft"]


def test_actual_command_exit_and_environment_are_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("PIP_AUDIT_DRY_RUN", "DOCKER_HOST", "GITLEAKS_CONFIG", "PYTHONPATH"):
        monkeypatch.setenv(name, "untrusted override")
    command = [
        sys.executable,
        "-I",
        "-c",
        "import os; print(sorted(os.environ)); raise SystemExit(7)",
    ]
    receipt = producer.execute("neutral", command, tmp_path, tmp_path)
    assert receipt["exit_code"] == 7
    assert receipt["command"] == command
    text = (tmp_path / "neutral.log").read_text()
    assert all(
        name not in text
        for name in ("PIP_AUDIT_DRY_RUN", "DOCKER_HOST", "GITLEAKS_CONFIG", "PYTHONPATH")
    )
    assert receipt["started_at"] <= receipt["completed_at"]


def test_unavailable_command_is_failure(tmp_path: Path) -> None:
    assert (
        producer.execute("missing", [str(tmp_path / "absent")], tmp_path, tmp_path)["exit_code"]
        == 127
    )


def test_scanner_interpreter_version_is_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, stdout=b"pip-audit 0.0.0\n"),
    )
    with pytest.raises(ValueError, match="wrong pip-audit version"):
        producer.verify_scanner_python(Path(sys.executable), tmp_path)


def test_frozen_export_uses_exact_bytes_and_executable_modes(tmp_path: Path) -> None:
    destination = tmp_path / "frozen"
    files = [
        (Path("regular.txt"), "0644", b"neutral\n"),
        (Path("tool.sh"), "0755", b"#!/bin/sh\nexit 0\n"),
    ]
    source.freeze_source(destination, files)
    source.verify_frozen_source(destination, files)
    assert os.access(destination / "tool.sh", os.X_OK)
    (destination / "tool.sh").chmod(0o644)
    with pytest.raises(ValueError, match="mode changed"):
        source.verify_frozen_source(destination, files)


@pytest.mark.parametrize("kind", ["symlink", "extra", "parent-symlink"])
def test_frozen_inventory_rejects_nonregular_or_added_members(tmp_path: Path, kind: str) -> None:
    destination = tmp_path / "frozen"
    files = [(Path("folder/neutral.txt"), "0644", b"neutral\n")]
    source.freeze_source(destination, files)
    external = tmp_path / "external"
    external.mkdir()
    (external / "neutral.txt").write_bytes(b"neutral\n")
    if kind == "symlink":
        (destination / "empty-link").symlink_to(external, target_is_directory=True)
    elif kind == "extra":
        (destination / "extra.txt").write_bytes(b"extra\n")
    else:
        (destination / "folder/neutral.txt").unlink()
        (destination / "folder").rmdir()
        (destination / "folder").symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError):
        source.verify_frozen_source(destination, files)


def test_runner_temp_inside_repository_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temporary = tmp_path / "runner"
    temporary.mkdir()
    monkeypatch.setenv("RUNNER_TEMP", str(temporary))
    with pytest.raises(ValueError, match="cannot enter the source"):
        source.runner_temporary(tmp_path)
