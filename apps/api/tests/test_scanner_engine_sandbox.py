"""Sandbox parity and safe export controls use no native container execution."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import scanner_engine_commands as commands
from scripts import scanner_engine_result as results
from scripts.source_security_commands import scanner_commands
from scripts.source_security_container import owned_command
from scripts.source_security_contract import IMAGES
from scripts.source_security_contract import SCHEMA as AUTHORITATIVE_SCHEMA
from scripts.source_security_gitleaks import gitleaks_arguments


def _sandbox(tmp_path: Path) -> commands.EngineSandbox:
    binary = tmp_path / "bin/gitleaks"
    binary.parent.mkdir()
    binary.write_bytes(b"neutral unit-only binary placeholder; never executed")
    output = tmp_path / "native"
    output.mkdir()
    return commands.EngineSandbox(
        tmp_path,
        output,
        tmp_path,
        binary,
        hashlib.sha256(binary.read_bytes()).hexdigest(),
        time.monotonic() + 1200,
    )


def _native_double(monkeypatch, *, code: int = 0, clean: bool = True) -> list[dict]:
    calls = []

    def execute(tool, command, output, cwd):
        actual, owned = owned_command(tool, command)
        record = {"tool": tool, "command": actual, "exit_code": code}
        if owned is not None:
            record["cleanup"] = {
                "owner": owned.owner,
                "name": owned.name,
                "container_id": "a" * 64,
                "status": "ABSENT" if clean else "UNPROVEN",
                "confirmed_absent": clean,
            }
        (output / f"{tool.replace(':', '-')}.log").write_bytes(b"neutral unit execution double\n")
        calls.append({"record": record, "cwd": cwd})
        return record

    monkeypatch.setattr(commands, "execute", execute)
    return calls


def test_alternate_full_invocation_changes_only_readonly_binary_mount_and_entrypoint(
    tmp_path,
) -> None:
    sandbox = _sandbox(tmp_path)
    commit = "a" * 40
    canonical = scanner_commands(
        tmp_path, tmp_path, sandbox.output, tmp_path, Path("/unused"), commit
    )["gitleaks"]
    observed = commands.engine_command(
        tmp_path, sandbox.output, tmp_path, sandbox.binary, gitleaks_arguments(commit)
    )
    image_index = canonical.index(IMAGES["gitleaks"])
    assert observed == [
        *canonical[:image_index],
        "--mount",
        f"type=bind,src={sandbox.binary.parent},dst=/diagnostic-bin,readonly",
        "--entrypoint",
        "/diagnostic-bin/gitleaks",
        *canonical[image_index:],
    ]
    assert commands.engine_command(tmp_path, sandbox.output, tmp_path, None, ["version"]) == [
        *canonical[: image_index + 1],
        "version",
    ]
    assert all(
        flag in observed
        for flag in (
            "--memory=2g",
            "--cpus=2",
            "--pids-limit=256",
            "--read-only",
            "--cap-drop=ALL",
            "GOMAXPROCS=2",
        )
    )
    assert observed[observed.index("--network") + 1] == "none"
    assert observed[observed.index("--timeout") + 1] == "230"
    assert (
        observed[observed.index("--log-opts") + 1]
        == f"{commit} --full-history --diff-merges=first-parent"
    )


@pytest.mark.parametrize("binary", [Path("gitleaks"), Path("/tmp/other")])
def test_binary_entrypoint_location_cannot_be_supplied_arbitrarily(tmp_path, binary) -> None:
    with pytest.raises(ValueError, match="binary location"):
        commands.engine_command(tmp_path, tmp_path, tmp_path, binary, ["version"])


@pytest.mark.parametrize("release", [True, False])
def test_native_double_records_owned_cleanup_before_returning(
    tmp_path, monkeypatch, release
) -> None:
    sandbox = _sandbox(tmp_path)
    calls = _native_double(monkeypatch)
    record, output = sandbox.run(
        "neutral-run", ["version"], release=release, source=tmp_path / "fixture"
    )
    assert sandbox.executions == [record] and calls[0]["cwd"] == tmp_path
    assert record["wall_seconds_including_owned_cleanup"] >= 0
    assert json.loads((output / "execution.json").read_bytes()) == record
    assert record["command"].count("--entrypoint") == int(release)
    assert f"type=bind,src={tmp_path / 'fixture'},dst=/source,readonly" in record["command"]


@pytest.mark.parametrize("code,clean", [(0, False), (127, True)])
def test_unverified_execution_or_cleanup_stops_the_probe(
    tmp_path, monkeypatch, code, clean
) -> None:
    sandbox = _sandbox(tmp_path)
    calls = _native_double(monkeypatch, code=code, clean=clean)
    with pytest.raises(ValueError):
        sandbox.run("neutral-run", ["version"], release=True)
    assert len(calls) == 1 and len(sandbox.executions) == 1


@pytest.mark.parametrize("poison", ["missing", "changed", "symlink"])
def test_binary_movement_is_rejected_before_container_start(tmp_path, monkeypatch, poison) -> None:
    sandbox = _sandbox(tmp_path)
    calls = _native_double(monkeypatch)
    if poison == "changed":
        sandbox.binary.write_bytes(b"different")
    else:
        sandbox.binary.unlink()
        if poison == "symlink":
            sandbox.binary.symlink_to(tmp_path / "missing-target")
    with pytest.raises(ValueError, match="binary changed"):
        sandbox.run("neutral-run", ["version"], release=True)
    assert calls == []


def test_job_budget_and_label_poison_stop_before_container_start(tmp_path, monkeypatch) -> None:
    sandbox = _sandbox(tmp_path)
    calls = _native_double(monkeypatch)
    with pytest.raises(ValueError, match="label"):
        sandbox.run("../outside", ["version"], release=True)
    monkeypatch.setattr(commands.time, "monotonic", lambda: sandbox.deadline - 299)
    with pytest.raises(ValueError, match="job budget"):
        sandbox.run("neutral-run", ["version"], release=True)
    assert calls == []


@pytest.mark.parametrize("trusted,code", [(True, 0), (True, 1), (False, 0)])
def test_only_one_pinned_image_is_provisioned(tmp_path, monkeypatch, trusted, code) -> None:
    sandbox = _sandbox(tmp_path)
    calls = _native_double(monkeypatch, code=code)
    monkeypatch.setattr(
        commands, "trusted_executable", lambda _: "/usr/bin/docker" if trusted else None
    )
    if trusted and code == 0:
        record = sandbox.pull_image()
        assert record["command"] == [
            "/usr/bin/docker",
            "--config",
            str(tmp_path / "docker-config"),
            "pull",
            "--platform",
            "linux/amd64",
            IMAGES["gitleaks"],
        ]
    else:
        with pytest.raises(ValueError):
            sandbox.pull_image()
    assert len(calls) == int(trusted)


def _report(output: Path, report: object = None, log: bytes = b"INF native summary\n") -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "gitleaks.log").write_bytes(log)
    (output / "gitleaks.json").write_text(json.dumps([] if report is None else report))


def _finding(**changes) -> dict:
    return {
        "RuleID": "neutral-engine-boundary",
        "File": "valid.txt",
        "Secret": "REDACTED",
        "Match": "REDACTED",
        **changes,
    }


@pytest.mark.parametrize(
    "report",
    [
        {},
        [None],
        [_finding(Secret="neutral-unredacted")],
        [_finding(Match=3)],
        [_finding(Fragment={"Raw": "neutral raw source"})],
        [_finding(Unexpected="payload")],
        [_finding(RuleID=None)],
        [_finding(File=None)],
    ],
)
def test_export_rejects_malformed_or_unredacted_native_reports(tmp_path, report) -> None:
    source, destination = tmp_path / "source", tmp_path / "destination"
    output = source / "release-full-history"
    _report(output, report)
    with pytest.raises(ValueError):
        results.export_outputs(source, destination)
    assert not (destination / "native/release-full-history/gitleaks.json").exists()


def test_export_keeps_original_regular_bytes_and_ignores_unrequested_files(tmp_path) -> None:
    source, destination = tmp_path / "source", tmp_path / "destination"
    output = source / "release-full-history"
    _report(output, [_finding(Match="surrounding REDACTED context")])
    (source / "unrequested-history.txt").write_text("neutral material must not be uploaded")
    profile = output / "gitleaks-profile/cpu.pprof"
    profile.parent.mkdir()
    profile.write_bytes(b"neutral profile bytes")
    inventory = results.export_outputs(source, destination)
    assert set(inventory) == {
        "release-full-history/gitleaks.log",
        "release-full-history/gitleaks.json",
        "release-full-history/gitleaks-profile/cpu.pprof",
    }
    for relative, metadata in inventory.items():
        original = (source / relative).read_bytes()
        assert (destination / "native" / relative).read_bytes() == original
        assert metadata == {"size": len(original), "sha256": hashlib.sha256(original).hexdigest()}
    assert not (destination / "native/unrequested-history.txt").exists()


def test_export_validates_the_exact_bytes_it_will_copy(tmp_path, monkeypatch) -> None:
    source, destination = tmp_path / "source", tmp_path / "destination"
    output = source / "release-full-history"
    _report(output)
    read_original = results.read_output
    reads = []

    def changing_read(path, root):
        if path.name == "gitleaks.json":
            reads.append(path)
            return (
                json.dumps([_finding(Secret="neutral unredacted")]).encode()
                if len(reads) == 1
                else b"[]"
            )
        return read_original(path, root)

    monkeypatch.setattr(results, "read_output", changing_read)
    with pytest.raises(ValueError, match="redact"):
        results.export_outputs(source, destination)
    assert len(reads) == 1
    assert not (destination / "native/release-full-history/gitleaks.json").exists()


def test_zero_exit_with_findings_is_a_contradictory_failed_observation(tmp_path) -> None:
    _report(tmp_path, [_finding()])
    result = results.full_observation({"exit_code": 0}, tmp_path)
    assert result["partial_or_failed"] is True
    assert result["findings_observed"] is True and result["zero_exit_with_findings"] is True
    assert result["history_completion_established"] is False


@pytest.mark.parametrize(
    "kind",
    [
        "symlink",
        "dangling",
        "parent-symlink",
        "directory",
        "fifo",
        "outside",
        "root-symlink",
        "oversized",
    ],
)
def test_native_output_path_and_resource_poison_is_refused(tmp_path, kind) -> None:
    root = tmp_path / "raw"
    root.mkdir()
    path = root / "output"
    outside = tmp_path / "outside"
    outside.write_bytes(b"neutral")
    if kind in {"symlink", "dangling"}:
        path.symlink_to(outside if kind == "symlink" else tmp_path / "missing")
    elif kind == "parent-symlink":
        path.symlink_to(tmp_path, target_is_directory=True)
        path /= "outside"
    elif kind == "directory":
        path.mkdir()
    elif kind == "fifo":
        os.mkfifo(path)
    elif kind == "outside":
        path = outside
    elif kind == "root-symlink":
        root.rmdir()
        root.symlink_to(tmp_path, target_is_directory=True)
        path = root / "outside"
    else:
        with path.open("wb") as stream:
            stream.truncate(results.MAX_OUTPUT_BYTES + 1)
    with pytest.raises((OSError, ValueError)):
        results.read_output(path, root)


def test_output_change_and_total_export_budget_are_refused(tmp_path, monkeypatch) -> None:
    root = tmp_path / "source"
    _report(root / "release-full-history")
    with monkeypatch.context() as patch:
        patch.setattr(
            results.os, "fstat", lambda _: SimpleNamespace(st_mode=stat.S_IFREG, st_size=1)
        )
        with pytest.raises(ValueError, match="changed while"):
            results.read_output(root / "release-full-history/gitleaks.log", root)
    monkeypatch.setattr(results, "MAX_EXPORT_BYTES", 1)
    with pytest.raises(ValueError, match="total byte budget"):
        results.export_outputs(root, tmp_path / "destination")


@pytest.mark.parametrize(
    "code,log,failed",
    [
        (0, b"INF normal summary", False),
        (1, b"WRN neutral finding", True),
        (124, b"", True),
        (0, b"SOURCE_SECURITY_TIMEOUT", True),
        (0, b"ERR [git] fatal: unable to read old blob", True),
        (0, b"\x1b[31mERR\x1b[0m read error", True),
        (0, b"FTL failed", True),
        (0, b"command aborted", True),
        (0, b"context deadline exceeded; partial scan", True),
        (0, b"timeout reached", True),
    ],
)
def test_clean_exit_never_hides_observed_input_errors_or_claims_eof(
    tmp_path, code, log, failed
) -> None:
    _report(tmp_path, log=log)
    result = results.full_observation({"exit_code": code}, tmp_path)
    assert result["partial_or_failed"] is failed
    assert result["eof_status"] == "NOT_INDEPENDENTLY_OBSERVED"
    assert result["history_completion_established"] is False
    assert result["native_report_valid"] is True
    receipt = results.diagnostic_receipt()
    assert receipt["schema"] != AUTHORITATIVE_SCHEMA
    assert receipt["not_authoritative"] is True and receipt["production_authorized"] is False
    assert receipt["drop_in_equivalence_established"] is False


@pytest.mark.parametrize("report", [b"{", b"null", b'[{"Secret":"REDACTED","Secret":"x"}]', None])
def test_unreadable_or_invalid_report_cannot_be_a_clean_native_result(tmp_path, report) -> None:
    (tmp_path / "gitleaks.log").write_bytes(b"normal summary")
    if report is not None:
        (tmp_path / "gitleaks.json").write_bytes(report)
    result = results.full_observation({"exit_code": 0}, tmp_path)
    assert result["partial_or_failed"] is True and result["native_report_valid"] is False
