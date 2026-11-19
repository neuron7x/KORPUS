"""Diagnostic orchestration doubles cannot manufacture native admission evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts import run_scanner_engine_diagnostic as runner
from scripts import scanner_engine_subject as subject
from scripts import source_security_execution, source_security_source
from scripts.scanner_engine_commands import EngineSandbox
from scripts.scanner_engine_result import diagnostic_receipt
from scripts.source_security_gitleaks import gitleaks_arguments

ROOT = Path(__file__).resolve().parents[3]


def _before() -> dict:
    return {
        "run": {
            "kind": "github-actions",
            "GITHUB_REPOSITORY": "neuron7x/KORPUS",
            "GITHUB_SHA": "a" * 40,
            "GITHUB_RUN_ID": "12345",
            "GITHUB_RUN_ATTEMPT": "2",
        },
        "source_commit_sha": "a" * 40,
        "source_tree_oid": "b" * 40,
        "source_before": {"sha256": "c" * 64},
    }


def _pull() -> dict:
    return {
        "pull_request": {
            "number": 116,
            "head": {"sha": "d" * 40, "ref": "ci/issue102"},
            "base": {"sha": "e" * 40, "ref": "main"},
        }
    }


def _event(tmp_path, monkeypatch, value) -> Path:
    path = tmp_path / "event.json"
    path.write_text(json.dumps(value))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_REF", "refs/pull/116/merge")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(path))
    return path


def test_pull_subject_distinguishes_checkout_from_reported_pr_head(tmp_path, monkeypatch) -> None:
    path = _event(tmp_path, monkeypatch, _pull())
    observed = subject.workflow_subject(_before())
    assert observed["checkout_sha"] == "a" * 40 and observed["checkout_tree"] == "b" * 40
    assert observed["head"] == {"sha": "d" * 40, "ref": "ci/issue102"}
    assert observed["run_id"] == "12345" and observed["run_attempt"] == "2"
    assert observed["event_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert observed["metadata_is_independent_attestation"] is False


@pytest.mark.parametrize("reference", ["refs/heads/main", "refs/tags/neutral-tag"])
def test_dispatched_subject_records_the_same_checkout_head(monkeypatch, reference) -> None:
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_REF", reference)
    observed = subject.workflow_subject(_before())
    assert observed["head"] == {"sha": "a" * 40, "ref": reference}


@pytest.mark.parametrize(
    "poison", ["repository", "event", "empty-ref", "spaced-ref", "dispatch-ref", "pull-ref"]
)
def test_wrong_workflow_subject_is_refused(tmp_path, monkeypatch, poison) -> None:
    _event(tmp_path, monkeypatch, _pull())
    before = _before()
    if poison == "repository":
        before["run"]["GITHUB_REPOSITORY"] = "unrelated/repository"
    if poison == "event":
        monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    if poison == "empty-ref":
        monkeypatch.delenv("GITHUB_REF")
    if poison == "spaced-ref":
        monkeypatch.setenv("GITHUB_REF", "refs/heads/a b")
    if poison == "dispatch-ref":
        monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
        monkeypatch.setenv("GITHUB_REF", "refs/pull/116/merge")
    if poison == "pull-ref":
        monkeypatch.setenv("GITHUB_REF", "refs/pull/117/merge")
    with pytest.raises(ValueError):
        subject.workflow_subject(before)


@pytest.mark.parametrize(
    "poison",
    [
        "not-object",
        "missing-pull",
        "missing-edge",
        "bad-sha",
        "empty-ref",
        "boolean-number",
        "zero-number",
        "oversize",
        "symlink",
    ],
)
def test_event_shape_and_file_poison_cannot_supply_subject_edges(
    tmp_path, monkeypatch, poison
) -> None:
    event = _pull()
    if poison == "not-object":
        event = []
    elif poison == "missing-pull":
        event = {}
    elif poison == "missing-edge":
        event["pull_request"]["head"] = None
    elif poison == "bad-sha":
        event["pull_request"]["head"]["sha"] = "different"
    elif poison == "empty-ref":
        event["pull_request"]["base"]["ref"] = ""
    elif poison == "boolean-number":
        event["pull_request"]["number"] = True
    elif poison == "zero-number":
        event["pull_request"]["number"] = 0
    path = _event(tmp_path, monkeypatch, event)
    if poison == "oversize":
        with path.open("wb") as stream:
            stream.truncate(2 * 1024 * 1024 + 1)
    if poison == "symlink":
        target = tmp_path / "elsewhere.json"
        path.rename(target)
        path.symlink_to(target)
    with pytest.raises((OSError, ValueError)):
        subject.workflow_subject(_before())


@pytest.mark.parametrize("count", [0, 21, 22, 23])
def test_full_diagnostic_cannot_change_the_22_record_baseline(tmp_path, count) -> None:
    baseline = json.dumps([{"unit_fixture": True}] * count).encode()
    (tmp_path / ".gitleaks-baseline.json").write_bytes(baseline)
    (tmp_path / ".gitleaks.toml").write_bytes(b"neutral unit configuration")
    if count != 22:
        with pytest.raises(ValueError, match="22 records"):
            subject.scanner_policy(tmp_path)
        return
    policy = subject.scanner_policy(tmp_path)
    assert policy["baseline_sha256"] == hashlib.sha256(baseline).hexdigest()
    assert policy["native_timeout_seconds"] == 230 and policy["parent_timeout_seconds"] == 240
    assert (
        policy["changed_authoritative_scanner"] is False and policy["default_max_decode_depth"] == 5
    )


def _prepared(tmp_path, monkeypatch, *, code=0, log=b"INF neutral summary\n", cleanup=True):
    root, temporary = tmp_path / "checkout", tmp_path / "temporary"
    root.mkdir()
    temporary.mkdir()
    (root / ".gitleaks-baseline.json").write_text(json.dumps([{}] * 22))
    (root / ".gitleaks.toml").write_text("neutral unit configuration")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/diagnostic")
    monkeypatch.setattr(runner, "admit_source", lambda _: (_before(), []))
    monkeypatch.setattr(runner, "runner_temporary", lambda _: temporary)
    monkeypatch.setattr(runner, "verify_source_after", lambda *_: "c" * 64)

    def acquire(destination):
        destination.mkdir()
        binary = destination / "gitleaks"
        binary.write_bytes(b"unit-only placeholder; never executed")
        return binary, {
            "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            "unit_double": True,
        }

    def run(sandbox, label, arguments, *, release, source=None):
        assert label == "release-full-history" and release is True and source is None
        assert arguments == gitleaks_arguments("a" * 40)
        output = sandbox.output / label
        output.mkdir()
        (output / "gitleaks.log").write_bytes(log)
        (output / "gitleaks.json").write_text("[]\n")
        record = {"tool": "unit-double", "exit_code": code}
        if not cleanup:
            record["tool"] = "gitleaks"
        sandbox.executions.append(record)
        return record, output

    monkeypatch.setattr(runner, "acquire_binary", acquire)
    monkeypatch.setattr(EngineSandbox, "pull_image", lambda _: {"unit_double": True})
    monkeypatch.setattr(EngineSandbox, "run", run)
    monkeypatch.setattr(runner, "versions", lambda _: {"unit_double": True})
    monkeypatch.setattr(
        runner, "utf8_probe", lambda _: {"expected_divergence_observed": True, "unit_double": True}
    )
    monkeypatch.setattr(runner, "damaged_history_probe", lambda _: {"unit_double": True})
    return root, root / "var/scanner-engine-diagnostic"


def test_clean_modeled_invocation_stays_nonauthoritative_and_eof_unknown(
    tmp_path, monkeypatch
) -> None:
    root, output = _prepared(tmp_path, monkeypatch)
    receipt = runner.produce(root, output)
    assert json.loads((output / "diagnostic.json").read_bytes()) == receipt
    assert receipt["status"] == "RECORDED_NONAUTHORITATIVE"
    assert receipt["not_authoritative"] is True and receipt["production_authorized"] is False
    assert receipt["drop_in_equivalence_established"] is False
    assert receipt["eof_status"] == "NOT_INDEPENDENTLY_OBSERVED"
    assert receipt["full_history"]["history_completion_established"] is False
    assert receipt["source_after_sha256"] == "c" * 64
    assert receipt["binary_unchanged_after_measurement"] is True
    assert len(receipt["output_inventory"]) == 2
    assert set(path.name for path in output.iterdir()) == {"native", "diagnostic.json"}


@pytest.mark.parametrize(
    "code,log",
    [
        (124, b"SOURCE_SECURITY_TIMEOUT"),
        (1, b"neutral failure"),
        (0, b"ERR fatal: unable to read old blob"),
        (0, b"partial scan"),
    ],
)
def test_partial_modeled_invocation_is_recorded_as_incomplete(
    tmp_path, monkeypatch, code, log
) -> None:
    root, output = _prepared(tmp_path, monkeypatch, code=code, log=log)
    receipt = runner.produce(root, output)
    assert receipt["status"] == "INCOMPLETE_DIAGNOSTIC"
    assert receipt["full_history"]["partial_or_failed"] is True
    assert receipt["source_after_sha256"] == "c" * 64
    assert receipt["not_authoritative"] is True and receipt["production_authorized"] is False


def test_unverified_container_cleanup_blocks_all_native_export(tmp_path, monkeypatch) -> None:
    root, output = _prepared(tmp_path, monkeypatch, cleanup=False)
    receipt = runner.produce(root, output)
    assert receipt["status"] == "INCOMPLETE_DIAGNOSTIC"
    assert "output_inventory" not in receipt and not (output / "native").exists()


def test_unreturned_native_execution_cannot_export_after_unproven_cleanup(
    tmp_path, monkeypatch
) -> None:
    original_run = EngineSandbox.run
    root, output = _prepared(tmp_path, monkeypatch)
    monkeypatch.setattr(EngineSandbox, "run", original_run)
    cleanup_calls = []

    def fail_after_start(command, _cwd, log):
        mount = next(value for value in command if value.endswith(",dst=/output"))
        native_output = Path(mount.split("src=", 1)[1].split(",dst=", 1)[0])
        (native_output / "gitleaks.json").write_text("[]\n")
        log.write(b"neutral exceptional native execution\n")
        raise subprocess.SubprocessError("unit child result unavailable")

    def unproven(owned, _environment):
        cleanup_calls.append(owned)
        return {"status": "UNPROVEN", "confirmed_absent": False}

    monkeypatch.setattr(source_security_execution, "_run", fail_after_start)
    monkeypatch.setattr(source_security_execution, "cleanup", unproven)
    receipt = runner.produce(root, output)
    assert len(cleanup_calls) == 1
    assert receipt["status"] == "INCOMPLETE_DIAGNOSTIC"
    assert "output_inventory" not in receipt and not (output / "native").exists()
    assert len(receipt["executions"]) == 1
    assert receipt["executions"][0]["execution_state"] == "PENDING"
    assert receipt["source_after_sha256"] == "c" * 64


def test_semantic_probe_mismatch_stops_before_full_history(tmp_path, monkeypatch) -> None:
    root, output = _prepared(tmp_path, monkeypatch)
    monkeypatch.setattr(runner, "utf8_probe", lambda _: {"expected_divergence_observed": False})
    monkeypatch.setattr(
        runner, "damaged_history_probe", lambda _: pytest.fail("continued after semantic mismatch")
    )
    receipt = runner.produce(root, output)
    assert receipt["utf8"]["expected_divergence_observed"] is False
    assert receipt["status"] == "INCOMPLETE_DIAGNOSTIC" and "full_history" not in receipt


@pytest.mark.parametrize("failure_stage", ["download", "export", "source-after"])
def test_failure_receipt_keeps_scope_and_does_not_leak_exception_query(
    tmp_path, monkeypatch, failure_stage
) -> None:
    root, output = _prepared(tmp_path, monkeypatch)

    def fail(*_):
        raise ValueError("unit signed-query-like payload must not be serialized")

    target = {
        "download": "acquire_binary",
        "export": "export_outputs",
        "source-after": "verify_source_after",
    }[failure_stage]
    monkeypatch.setattr(runner, target, fail)
    receipt = runner.produce(root, output)
    assert receipt["status"] == "INCOMPLETE_DIAGNOSTIC" and receipt["failure_class"] == "ValueError"
    assert "signed-query" not in (output / "diagnostic.json").read_text()
    expected_stage = {
        "download": "fixed-release-download",
        "export": "safe-native-output-export",
        "source-after": "source-after-verification",
    }[failure_stage]
    assert receipt["stage"] == expected_stage


def test_output_must_be_fresh_and_cannot_escape_through_symlink(tmp_path) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    with pytest.raises(ValueError, match="outside"):
        runner.produce(root, tmp_path / "outside")
    with pytest.raises(ValueError, match="outside"):
        runner.produce(root, root / "../outside")
    (root / "var").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        runner.produce(root, root / "var/diagnostic")


@pytest.mark.parametrize(
    "status,expected", [("RECORDED_NONAUTHORITATIVE", 0), ("INCOMPLETE_DIAGNOSTIC", 1)]
)
def test_cli_exit_is_separate_from_admission_authority(
    monkeypatch, capsys, status, expected
) -> None:
    receipt = {**diagnostic_receipt(), "status": status}
    monkeypatch.setattr(runner, "produce", lambda *_: receipt)
    assert runner.main() == expected
    observed = json.loads(capsys.readouterr().out)
    assert (
        observed["not_authoritative"] is True
        and observed["eof_status"] == "NOT_INDEPENDENTLY_OBSERVED"
    )


def test_entrypoint_refuses_source_admission_without_native_execution(
    tmp_path, monkeypatch
) -> None:
    def refuse(_):
        raise ValueError("unit source admission refusal")

    monkeypatch.setattr(source_security_source, "admit_source", refuse)
    monkeypatch.setattr(sys, "path", sys.path.copy())
    path = ROOT / "scripts/run_scanner_engine_diagnostic.py"
    # Execute unchanged entrypoint bytes, with __file__ confined to this unit's
    # directory; the source guard refuses before download or container execution.
    namespace = {"__name__": "__main__", "__file__": str(tmp_path / "scripts/runner.py")}
    with pytest.raises(SystemExit) as stopped:
        exec(compile(path.read_text(), str(path), "exec"), namespace)
    assert stopped.value.code == 1
    receipt = json.loads((tmp_path / "var/scanner-engine-diagnostic/diagnostic.json").read_bytes())
    assert receipt["status"] == "INCOMPLETE_DIAGNOSTIC" and "release" not in receipt


def test_separate_workflow_has_no_admission_permissions_or_authoritative_artifact_name() -> None:
    path = ROOT / ".github/workflows/scanner-engine-diagnostic.yml"
    workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"pull_request", "workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] == "false"
    job = workflow["jobs"]["native-engine-observation"]
    assert job["timeout-minutes"] == "25" and job["runs-on"] == "ubuntu-24.04"
    steps = job["steps"]
    assert steps[0]["uses"] == "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
    assert steps[0]["with"] == {"fetch-depth": "0", "persist-credentials": "false"}
    assert steps[1]["uses"] == "actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0"
    assert steps[-1]["uses"] == "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9"
    assert steps[-1]["with"]["name"] == "scanner-engine-diagnostic-${{ github.run_attempt }}"
    assert steps[-1]["with"]["path"] == "var/scanner-engine-diagnostic/"
    assert (
        "GITHUB_TOKEN" not in path.read_text()
        and "source-security-evidence" not in path.read_text()
    )
