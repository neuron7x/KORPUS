"""Owned container removal, including a real process behind a modeled daemon."""

from __future__ import annotations

import copy
import os
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

import pytest

from scripts import source_security_container as containers
from scripts import source_security_execution as execution
from scripts.source_security_contract import IMAGES


class DockerModel:
    """Model daemon ownership; normal subprocess tests still execute native processes."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.active = False
        self.owner = ""
        self.cid = "c" * 64
        self.removed: list[str] = []

    def run(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        if command[3] == "run":
            assert kwargs["timeout"] == (630 if IMAGES["gitleaks"] in command else 240)
            self.owner = command[command.index("--label") + 1].split("=", 1)[1]
            if self.mode != "no-cid":
                Path(command[command.index("--cidfile") + 1]).write_text(self.cid)
            self.active = self.mode != "success"
            if self.mode in {"timeout", "no-cid"}:
                if self.mode == "no-cid":
                    self.active = False
                raise subprocess.TimeoutExpired(command, 240)
            return subprocess.CompletedProcess(command, 0)
        assert command[3] == "container" and kwargs["timeout"] == 10
        action = command[4]
        if action == "ls":
            if self.mode == "query-error":
                return subprocess.CompletedProcess(command, 1, stdout=b"", stderr=b"daemon failed")
            output = (self.cid + "\n").encode() if self.active else b""
        elif action == "inspect":
            token = "f" * 32 if self.mode == "foreign-owner" else self.owner
            output = (self.cid + " " + token + "\n").encode()
        elif action == "rm":
            assert command[-1] == self.cid
            self.removed.append(command[-1])
            self.active = self.mode == "survivor"
            output = (self.cid + "\n").encode()
        else:
            raise AssertionError(command)
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr=b"")


def command(tmp_path: Path, tool: str = "gitleaks") -> list[str]:
    return [
        "/usr/bin/docker",
        "--config",
        str(tmp_path / "docker-config"),
        "run",
        "--rm",
        IMAGES[tool],
    ]


@pytest.mark.parametrize("tool", list(IMAGES))
@pytest.mark.parametrize("mode", ["success", "retained", "timeout"])
def test_known_owned_container_is_absent_after_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: str, mode: str
) -> None:
    model = DockerModel(mode)
    monkeypatch.setattr(subprocess, "run", model.run)
    receipt = execution.execute(tool, command(tmp_path, tool), tmp_path, tmp_path)
    assert receipt["exit_code"] == (124 if mode == "timeout" else 0)
    assert receipt["cleanup"]["confirmed_absent"] is True
    assert containers.cleanup_valid(receipt)
    assert not model.active
    assert model.removed == ([] if mode == "success" else [model.cid])
    assert execution.execution_succeeded(receipt) is (mode != "timeout")


@pytest.mark.parametrize("mode", ["no-cid", "query-error", "foreign-owner", "survivor"])
def test_unproven_cleanup_cannot_pass_or_delete_unknown_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    model = DockerModel(mode)
    monkeypatch.setattr(subprocess, "run", model.run)
    receipt = execution.execute("gitleaks", command(tmp_path), tmp_path, tmp_path)
    assert receipt["exit_code"] != 0
    assert receipt["cleanup"]["confirmed_absent"] is False
    assert not execution.execution_succeeded(receipt)
    if mode != "survivor":
        assert model.removed == []


@pytest.mark.parametrize(
    "poison", ["missing", "absent-false", "foreign-name", "foreign-label", "bad-id"]
)
def test_zero_exit_cannot_hide_missing_or_foreign_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, poison: str
) -> None:
    model = DockerModel("success")
    monkeypatch.setattr(subprocess, "run", model.run)
    receipt = execution.execute("gitleaks", command(tmp_path), tmp_path, tmp_path)
    assert execution.execution_succeeded(receipt)
    record = copy.deepcopy(receipt)
    if poison == "missing":
        del record["cleanup"]
    elif poison == "absent-false":
        record["cleanup"]["confirmed_absent"] = False
    elif poison == "foreign-name":
        record["cleanup"]["name"] = "unowned"
    elif poison == "foreign-label":
        record["command"][record["command"].index("--label") + 1] = "unowned=value"
    else:
        record["cleanup"]["container_id"] = "not-a-container-id"
    assert not execution.execution_succeeded(record)


def test_timeout_removes_real_worker_behind_modeled_daemon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_run = subprocess.run
    model = DockerModel("timeout")
    marker = tmp_path / "late-output"
    worker: subprocess.Popen[bytes] | None = None

    def run(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        nonlocal worker
        if arguments[3] == "run":
            with suppress(subprocess.TimeoutExpired):
                model.run(arguments, **kwargs)
            worker = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    "import time,pathlib,sys; time.sleep(.6); pathlib.Path(sys.argv[1]).write_text('late')",
                    str(marker),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            kwargs["timeout"] = 0.1
            return real_run([sys.executable, "-I", "-c", "import time; time.sleep(5)"], **kwargs)
        if arguments[4] == "rm":
            assert worker is not None
            worker.kill()
            worker.wait(timeout=5)
        return model.run(arguments, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    try:
        receipt = execution.execute("gitleaks", command(tmp_path), tmp_path, tmp_path)
        assert receipt["exit_code"] == 124 and receipt["cleanup"]["confirmed_absent"]
        assert worker is not None and worker.poll() is not None
        time.sleep(0.65)
        assert not marker.exists(), "owned worker mutated scanner output after timeout"
    finally:
        if worker is not None and worker.poll() is None:
            worker.kill()
            worker.wait(timeout=5)


@pytest.mark.parametrize("kind", ["malformed", "symlink"])
def test_unsafe_cidfile_is_not_an_authority_for_removal(tmp_path: Path, kind: str) -> None:
    _, owned = containers.owned_command("gitleaks", command(tmp_path))
    assert owned is not None
    if kind == "malformed":
        owned.cidfile.write_text("unowned")
    else:
        target = tmp_path / "external"
        target.write_text("c" * 64)
        owned.cidfile.symlink_to(target)
    result = containers.cleanup(owned, execution.environment())
    assert result["confirmed_absent"] is False


def test_container_names_are_unique_and_private_to_each_execution(tmp_path: Path) -> None:
    a, first = containers.owned_command("gitleaks", command(tmp_path))
    b, second = containers.owned_command("gitleaks", command(tmp_path))
    assert first is not None and second is not None
    assert first.name != second.name and first.cidfile != second.cidfile
    assert first.cidfile.parent == tmp_path
    assert "--rm" in a and "--rm" in b
    assert os.path.isabs(first.cidfile)


@pytest.mark.parametrize("tool", ["pip-audit:runtime", "pip-audit:dev", "image:gitleaks"])
def test_non_history_executions_keep_the_existing_parent_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: str
) -> None:
    def run(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        assert kwargs["timeout"] == 240
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(subprocess, "run", run)
    receipt = execution.execute(tool, ["/fixed/executable"], tmp_path, tmp_path)
    assert receipt["exit_code"] == 0
    assert "cleanup" not in receipt


@pytest.mark.parametrize("mode", ["owned", "foreign-owner", "not-created"])
def test_timeout_during_creation_resolves_empty_cid_by_owned_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    """Docker opens the CID file before its create response can supply an ID."""

    class CreationRace(DockerModel):
        def run(self, arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
            if arguments[3] == "run":
                self.owner = arguments[arguments.index("--label") + 1].split("=", 1)[1]
                Path(arguments[arguments.index("--cidfile") + 1]).write_bytes(b"")
                # Existence models a created, not yet started, daemon container.
                self.active = mode != "not-created"
                raise subprocess.TimeoutExpired(arguments, 240)
            return super().run(arguments, **kwargs)

    model = CreationRace(mode)
    monkeypatch.setattr(subprocess, "run", model.run)
    receipt = execution.execute("gitleaks", command(tmp_path), tmp_path, tmp_path)
    assert receipt["exit_code"] == 124
    assert receipt["cleanup"]["confirmed_absent"] is (mode == "owned")
    assert model.removed == ([model.cid] if mode == "owned" else [])
    assert model.active is (mode == "foreign-owner")
    assert not execution.execution_succeeded(receipt)
