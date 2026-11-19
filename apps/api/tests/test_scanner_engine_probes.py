"""Real disposable Git controls; scanner observations below are explicitly unit doubles."""

from __future__ import annotations

import hashlib
import json
import subprocess
import zlib
from pathlib import Path

import pytest

from scripts import scanner_engine_fixtures as fixtures
from scripts import scanner_engine_probes as probes


@pytest.fixture
def fixture_git(monkeypatch):
    # Only neutral temporary repositories use this unit injection. Production's
    # root-owned executable admission is unchanged and tested separately below.
    monkeypatch.setattr(fixtures, "git_executable", lambda: "/usr/bin/git")


class ProbeDouble:
    def __init__(self, temporary: Path, overrides: dict | None = None) -> None:
        self.temporary, self.overrides, self.calls = temporary, overrides or {}, []

    def run(self, label, arguments, *, release, source=None):
        self.calls.append(label)
        assert release == label.startswith("release")
        output = self.temporary / ("output-" + label)
        output.mkdir()
        changed = self.overrides.get(label, {})
        if label.endswith("version"):
            log = changed.get("version", "8.30.1" if release else "v8.30.1")
            assert arguments == ["version"] and source is None
            code = changed.get("code", 0)
        else:
            assert source is not None and arguments[arguments.index("--timeout") + 1] == "15"
            assert "--redact" in arguments and "--config" in arguments
            engine = changed.get("engine", probes.ENGINES["release" if release else "stdlib"])
            log = "DBG using " + engine + " regex engine\n" + changed.get("extra_log", "")
            files = ["valid.txt"] if release else ["invalid.txt", "valid.txt"]
            if "history" in label:
                files = ["deleted.txt"] if label.endswith("intact") else []
            code = changed.get("code", 1 if files else 0)
            report = changed.get(
                "report",
                [
                    {
                        "RuleID": "neutral-engine-boundary",
                        "File": name,
                        "Match": "REDACTED",
                        "Secret": "REDACTED",
                    }
                    for name in changed.get("files", files)
                ],
            )
            if report is not None:
                (output / "gitleaks.json").write_text(json.dumps(report))
        (output / "gitleaks.log").write_text(log + "\n")
        return {"exit_code": code, "unit_double": True}, output


def test_utf8_fixture_preserves_invalid_byte_in_real_git_patch(tmp_path, fixture_git) -> None:
    source = tmp_path / "utf8"
    head = fixtures.utf8_fixture(source)
    stream = fixtures.checked_git(source, ["log", "-p", "-U0", head])
    assert b"+" + fixtures.INVALID_TEXT in stream
    assert b"+" + fixtures.VALID_TEXT in stream
    assert (source / "canary.toml").read_bytes() == fixtures.CANARY_CONFIG
    assert "canary.toml" not in fixtures.checked_git(source, ["ls-files"]).decode()


def test_damage_removes_only_old_blob_and_preserves_current_tree(tmp_path, fixture_git) -> None:
    source = tmp_path / "history"
    identity = fixtures.history_fixture(source)
    object_dir = source / ".git/objects"
    before = {
        path.relative_to(object_dir): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in object_dir.rglob("*")
        if path.is_file()
    }
    controls = fixtures.history_control(source, identity["head"])
    assert [item["exit_code"] for item in controls.values()] == [0, 0]
    intact = fixtures.checked_git(source, ["log", "-p", "-U0", identity["head"]])
    assert b"+" + fixtures.VALID_TEXT in intact
    fixtures.damage_history(source, identity)
    after = {
        path.relative_to(object_dir): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in object_dir.rglob("*")
        if path.is_file()
    }
    blob = identity["deleted_blob"]
    removed = Path(blob[:2]) / blob[2:]
    assert set(before) - set(after) == {removed}
    assert after == {path: digest for path, digest in before.items() if path != removed}
    assert (source / "current.txt").read_text() == "neutral current content\n"
    damaged = fixtures.history_control(source, identity["head"])
    assert damaged["git_log"]["exit_code"] == 128 and damaged["git_fsck"]["exit_code"] == 2


@pytest.mark.parametrize(
    "case", ["invalid-id", "symlink", "wrong-content", "oversized", "changed-head"]
)
def test_historical_removal_requires_the_exact_owned_fixture_blob(
    tmp_path, fixture_git, case
) -> None:
    source = tmp_path / "history"
    identity = fixtures.history_fixture(source)
    blob = identity["deleted_blob"]
    path = source / ".git/objects" / blob[:2] / blob[2:]
    if case == "invalid-id":
        identity["deleted_blob"] = "../../outside"
    elif case == "symlink":
        original = tmp_path / "original"
        path.rename(original)
        path.symlink_to(original)
    elif case == "wrong-content":
        path.chmod(0o600)
        path.write_bytes(zlib.compress(b"blob 7\0neutral"))
    elif case == "oversized":
        path.chmod(0o600)
        path.write_bytes(b"x" * 1024)
    else:
        identity["head"] = "f" * 40
    with pytest.raises(ValueError):
        fixtures.damage_history(source, identity)


def test_neutral_fixture_refuses_untrusted_git(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(fixtures, "git_executable", lambda: None)
    with pytest.raises(ValueError, match="trusted Git"):
        fixtures.fixture_git(tmp_path, ["status"])


def test_neutral_fixture_construction_does_not_ignore_git_errors(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        fixtures,
        "fixture_git",
        lambda *_: subprocess.CompletedProcess([], 128, b"", b"neutral error"),
    )
    with pytest.raises(ValueError, match="construction failed"):
        fixtures.checked_git(tmp_path, ["status"])


def test_versions_record_actual_narrow_format_without_build_attestation(tmp_path) -> None:
    result = probes.versions(ProbeDouble(tmp_path))
    assert result["stdlib"]["reported_version"] == "v8.30.1"
    assert result["release"]["reported_version"] == "8.30.1"


@pytest.mark.parametrize(
    "change", [{"version": "8.30.2"}, {"version": "extra output 8.30.1"}, {"code": 1}]
)
def test_wrong_or_failed_native_version_stops_further_calls(tmp_path, change) -> None:
    sandbox = ProbeDouble(tmp_path, {"stdlib-version": change})
    with pytest.raises(ValueError, match="version probe"):
        probes.versions(sandbox)
    assert sandbox.calls == ["stdlib-version"]


def test_paired_native_double_records_semantic_divergence_not_equivalence(
    tmp_path, fixture_git
) -> None:
    result = probes.utf8_probe(ProbeDouble(tmp_path))
    assert result["expected_divergence_observed"] is True
    assert result["observations"]["stdlib"]["finding_files"] == ["invalid.txt", "valid.txt"]
    assert result["observations"]["release"]["finding_files"] == ["valid.txt"]
    assert result["valid_input_sha256"] != result["invalid_input_sha256"]
    assert "equivalence" not in result


@pytest.mark.parametrize(
    "change",
    [
        {"files": ["valid.txt"]},
        {"files": []},
        {"code": 0},
        {"engine": "unverified-engine"},
        {"report": None},
        {"report": {}},
        {
            "report": [
                {"RuleID": "wrong", "File": "valid.txt", "Secret": "REDACTED", "Match": "REDACTED"}
            ]
        },
        {
            "report": [
                {
                    "RuleID": "neutral-engine-boundary",
                    "File": "valid.txt",
                    "Secret": "REDACTED",
                    "Match": "unredacted context",
                }
            ]
        },
        {"extra_log": "context deadline exceeded; partial scan"},
        {"extra_log": "ERR [git] fatal: unable to read historical blob"},
        {"extra_log": "command aborted"},
        {"extra_log": "DBG using github.com/wasilibs/go-re2 regex engine"},
        {"extra_log": "DBG using unknown-extra-engine regex engine"},
        {"extra_log": "DBG using stdlib regex engine"},
    ],
)
def test_partial_or_poisoned_utf8_observations_cannot_establish_expected_divergence(
    tmp_path, fixture_git, change
) -> None:
    result = probes.utf8_probe(ProbeDouble(tmp_path, {"stdlib-utf8": change}))
    assert result["expected_divergence_observed"] is False
    assert "stdlib" in result["observations"] and "release" in result["observations"]


def test_unverified_utf8_execution_stops_before_the_second_engine(tmp_path, fixture_git) -> None:
    sandbox = ProbeDouble(tmp_path, {"stdlib-utf8": {"code": 124}})
    with pytest.raises(ValueError, match="execution is incomplete"):
        probes.utf8_probe(sandbox)
    assert sandbox.calls == ["stdlib-utf8"]


@pytest.mark.parametrize("damaged_code", [0, 1])
def test_damaged_history_records_native_outcome_without_presuming_error_propagation(
    tmp_path, fixture_git, damaged_code
) -> None:
    changes = {
        name + "-history-damaged": {
            "code": damaged_code,
            "extra_log": "ERR fatal: unable to read historical blob\ncommand aborted",
        }
        for name in probes.ENGINES
    }
    sandbox = ProbeDouble(tmp_path, changes)
    result = probes.damaged_history_probe(sandbox)
    for name in probes.ENGINES:
        assert result["observations"]["intact"][name]["finding_files"] == ["deleted.txt"]
        assert result["observations"]["damaged"][name]["execution"]["exit_code"] == damaged_code
        assert (
            result["observations"]["damaged"][name]["diagnostics"]["native_error_message_observed"]
            is True
        )
    assert "NOT_INDEPENDENTLY_OBSERVED" in result["interpretation"]
    assert len(sandbox.calls) == 4


@pytest.mark.parametrize(
    "label,change",
    [
        ("stdlib-history-intact", {"files": []}),
        ("stdlib-history-intact", {"extra_log": "partial scan"}),
        ("stdlib-history-intact", {"code": 0}),
        ("stdlib-history-damaged", {"code": 124}),
        ("stdlib-history-damaged", {"engine": "wrong"}),
    ],
)
def test_history_control_poison_stops_subsequent_native_calls(
    tmp_path, fixture_git, label, change
) -> None:
    sandbox = ProbeDouble(tmp_path, {label: change})
    with pytest.raises(ValueError):
        probes.damaged_history_probe(sandbox)
    assert sandbox.calls[-1] == label


def test_git_controls_must_independently_establish_damage(
    tmp_path, fixture_git, monkeypatch
) -> None:
    monkeypatch.setattr(
        probes,
        "history_control",
        lambda *_: {"git_log": {"exit_code": 0}, "git_fsck": {"exit_code": 0}},
    )
    sandbox = ProbeDouble(tmp_path)
    with pytest.raises(ValueError, match="independent Git controls"):
        probes.damaged_history_probe(sandbox)
    assert sandbox.calls == ["stdlib-history-intact", "release-history-intact"]
