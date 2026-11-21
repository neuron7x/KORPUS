"""Orchestration doubles test refusal paths; none are native scanner evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from scripts import run_scanner_stdlib_diagnostic as runner
from scripts import scanner_engine_result as engine_results
from scripts import scanner_stdlib_probes as probes
from scripts.scanner_stdlib_result import diagnostic_receipt, export_outputs
from scripts.source_security_gitleaks import gitleaks_arguments

ROOT = Path(__file__).resolve().parents[3]


def _finding(rule, file, column=1):
    return {
        "RuleID": rule,
        "File": file,
        "StartColumn": column,
        "Secret": "REDACTED",
        "Match": "REDACTED",
    }


def _native(tmp_path, label, records, *, marker="stdlib", version=False):
    output = tmp_path / label
    output.mkdir()
    (output / "gitleaks.log").write_text(
        "v8.30.1" if version else f"DBG using {marker} regex engine\n"
    )
    (output / "gitleaks.json").write_text(json.dumps(records))
    return {"exit_code": 0 if version else 1}, output


@pytest.mark.parametrize(
    "poison",
    [None, "missing-invalid", "changed-offset", "alternate-engine", "extra-rule", "extra-file"],
)
def test_paired_controls_require_both_utf8_files_and_identical_full_records(
    tmp_path, monkeypatch, poison
) -> None:
    monkeypatch.setattr(probes, "utf8_fixture", lambda _: "a" * 40)
    monkeypatch.setattr(probes, "positive_fixture", lambda _: "b" * 40)

    def invoke(label, arguments, **_):
        records = []
        if label.endswith("utf8"):
            files = ["invalid.txt", "valid.txt"]
            if label.startswith("candidate") and poison == "missing-invalid":
                files = ["valid.txt"]
            records = [_finding("neutral-engine-boundary", name) for name in files]
        elif label.endswith("positive"):
            column = 2 if label.startswith("candidate") and poison == "changed-offset" else 1
            records = [_finding(rule, "positive.txt", column) for rule in sorted(probes.RULE_IDS)]
            if poison == "extra-rule":
                records.append(_finding("unit-unexpected-rule", "positive.txt"))
            if poison == "extra-file":
                records[0]["File"] = "unit-unexpected-file.txt"
        marker = "github.com/wasilibs/go-re2" if poison == "alternate-engine" else "stdlib"
        return _native(tmp_path, label, records, marker=marker, version=label.endswith("version"))

    sandbox = SimpleNamespace(temporary=tmp_path, run=invoke)
    if poison:
        with pytest.raises(ValueError):
            probes.paired_probes({"control": sandbox, "candidate": sandbox})
    else:
        observed = probes.paired_probes({"control": sandbox, "candidate": sandbox})
        assert observed["identical_positive_and_utf8_records"] is True
        assert observed["utf8"]["candidate"]["finding_count"] == 2


@pytest.mark.parametrize("candidate_partial", [False, True])
def test_full_history_keeps_fixed_arguments_and_cannot_promote_partial_candidate(
    tmp_path, monkeypatch, candidate_partial
) -> None:
    monkeypatch.setattr(
        runner, "paired_probes", lambda _: {"identical_positive_and_utf8_records": True}
    )
    monkeypatch.setattr(
        runner, "full_observation", lambda execution, _: {"partial_or_failed": execution["partial"]}
    )
    calls = []

    def invoke(label, arguments, **kwargs):
        calls.append((label, arguments, kwargs))
        return {"partial": label.startswith("control") or candidate_partial}, tmp_path

    sandbox = SimpleNamespace(pull_image=lambda: {}, run=invoke, verify_binary=lambda: None)
    receipt = diagnostic_receipt()
    if candidate_partial:
        with pytest.raises(ValueError, match="candidate native"):
            runner.measure({"control": sandbox, "candidate": sandbox}, "a" * 40, receipt)
        assert receipt["status"] == "INCOMPLETE_DIAGNOSTIC"
    else:
        runner.measure({"control": sandbox, "candidate": sandbox}, "a" * 40, receipt)
        assert receipt["status"] == "RECORDED_NONAUTHORITATIVE"
    assert len(calls) == 2 and all(item[1] == gitleaks_arguments("a" * 40) for item in calls)
    assert receipt["not_authoritative"] is True and receipt["production_authorized"] is False
    assert receipt["eof_status"] == "NOT_INDEPENDENTLY_OBSERVED"
    assert receipt["history_completion_established"] is False


def test_receipt_does_not_serialize_exception_payload(tmp_path, monkeypatch) -> None:
    def fail(*_):
        raise ValueError("neutral private-query sentinel")

    monkeypatch.setattr(runner, "experiment", fail)
    receipt = runner.produce(tmp_path, tmp_path / "var/diagnostic")
    assert receipt["status"] == "INCOMPLETE_DIAGNOSTIC"
    assert receipt["failure_class"] == "ValueError"
    assert "private-query" not in (tmp_path / "var/diagnostic/diagnostic.json").read_text()


def test_output_path_cannot_escape_or_follow_symlink(tmp_path) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    with pytest.raises(ValueError):
        runner.produce(root, tmp_path / "outside")
    (root / "var").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        runner.produce(root, root / "var/diagnostic")


def test_export_rejects_unredacted_findings(tmp_path) -> None:
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    output = source / "candidate-utf8"
    output.mkdir()
    record = _finding("neutral-engine-boundary", "valid.txt")
    record["Secret"] = "unit unredacted sentinel"
    (output / "gitleaks.json").write_text(json.dumps([record]))
    with pytest.raises(ValueError, match="redact"):
        export_outputs(source, destination)


@pytest.mark.parametrize(
    "exporter,label",
    [
        (export_outputs, "candidate-full-history"),
        (engine_results.export_outputs, "release-full-history"),
    ],
)
def test_export_removes_all_corpus_text_and_raw_profile_strings(tmp_path, exporter, label) -> None:
    source, destination = tmp_path / "source", tmp_path / "destination"
    native = source / label
    native.mkdir(parents=True)
    sentinel = "unit-private-corpus-sentinel"
    record = _finding("unit-rule", sentinel)
    for field in (
        "Match",
        "Message",
        "Author",
        "Email",
        "SymlinkFile",
        "Link",
        "Description",
        "Fingerprint",
    ):
        record[field] = sentinel
    record["Tags"] = [sentinel]
    report = json.dumps([record]).encode()
    (native / "gitleaks.json").write_bytes(report)
    log = f"INF 123 commits scanned.\nINF scanned ~456 bytes\n{sentinel}\n".encode()
    (native / "gitleaks.log").write_bytes(log)
    (native / "execution.json").write_text(sentinel)
    profile = native / "gitleaks-profile"
    profile.mkdir()
    (profile / "cpu.pprof").write_text(sentinel)
    inventory = exporter(source, destination)
    assert len(inventory) == 4
    outputs = [path for path in destination.rglob("*") if path.is_file()]
    assert all(path.name.endswith(".summary.json") for path in outputs)
    assert all(sentinel.encode() not in path.read_bytes() for path in outputs)
    summaries = {
        json.loads(path.read_bytes())["source_name"]: json.loads(path.read_bytes())
        for path in outputs
    }
    report_summary = summaries[label + "/gitleaks.json"]
    assert report_summary["source_sha256"] == hashlib.sha256(report).hexdigest()
    assert report_summary["source_bytes"] == len(report) and report_summary["finding_count"] == 1
    log_summary = summaries[label + "/gitleaks.log"]
    assert log_summary["reported_commits"] == 123 and log_summary["reported_bytes"] == 456
    assert all(item["raw_content_exported"] is False for item in summaries.values())


@pytest.mark.parametrize("symlink", [False, True])
def test_source_configuration_override_is_refused_before_build(
    tmp_path, monkeypatch, symlink
) -> None:
    override = tmp_path / ".gitleaks.toml"
    if symlink:
        override.symlink_to("missing-neutral-target")
    else:
        override.write_text('title = "unit override"')
    monkeypatch.setattr(runner, "admit_source", lambda _: ({"source_commit_sha": "a" * 40}, []))
    monkeypatch.setattr(runner, "workflow_subject", lambda _: {})
    monkeypatch.setattr(runner, "scanner_policy", lambda _: {})
    monkeypatch.setattr(runner, "runner_temporary", lambda _: pytest.fail("continued to build"))
    monkeypatch.setattr(runner, "verify_source_after", lambda *_: "b" * 64)
    receipt = diagnostic_receipt()
    with pytest.raises(ValueError, match="source-provided"):
        runner.experiment(tmp_path, tmp_path / "output", receipt)
    assert receipt["source_after_sha256"] == "b" * 64
    assert "source_configuration_override_absent" not in receipt


def test_diagnostic_workflow_has_no_admission_permissions_or_artifact_name() -> None:
    path = ROOT / ".github/workflows/scanner-stdlib-diagnostic.yml"
    workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["on"]) == {"pull_request", "workflow_dispatch"}
    steps = workflow["jobs"]["paired-native-stdlib-observation"]["steps"]
    assert steps[0]["with"] == {"fetch-depth": "0", "persist-credentials": "false"}
    compiler = next(step for step in steps if "install_scanner_compiler.py" in step.get("run", ""))
    assert '--destination "$RUNNER_TEMP/korpus-pinned-go"' in compiler["run"]
    assert '"$RUNNER_TEMP/korpus-pinned-go/go/bin" >> "$GITHUB_PATH"' in compiler["run"]
    assert steps[-1]["with"]["name"] == "scanner-stdlib-diagnostic-${{ github.run_attempt }}"
    assert (
        "source-security-evidence" not in path.read_text()
        and "GITHUB_TOKEN" not in path.read_text()
    )
