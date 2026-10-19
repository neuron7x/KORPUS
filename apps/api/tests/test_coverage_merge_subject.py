"""Real branch datasets exercise the boundary between producers and the union gate.

The small programs are deliberately independent of KORPUS database infrastructure:
they prove coverage accounting and execution provenance, not PostgreSQL behaviour.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from merge_dialect_coverage import same_subject  # noqa: E402

GITHUB_FIELDS = (
    "GITHUB_ACTIONS",
    "GITHUB_REPOSITORY",
    "GITHUB_SHA",
    "GITHUB_RUN_ID",
    "GITHUB_RUN_ATTEMPT",
)
GITLAB_FIELDS = ("GITLAB_CI", "CI_PROJECT_PATH", "CI_COMMIT_SHA", "CI_PIPELINE_ID", "CI_JOB_ID")
HOSTED = {
    "GITHUB_ACTIONS": "true",
    "GITHUB_REPOSITORY": "neuron7x/KORPUS",
    "GITHUB_SHA": "a" * 40,
    "GITHUB_RUN_ID": "123",
    "GITHUB_RUN_ATTEMPT": "1",
}
GITLAB = {
    "GITLAB_CI": "true",
    "CI_PROJECT_PATH": "group/subgroup/KORPUS",
    "CI_COMMIT_SHA": "a" * 40,
    "CI_PIPELINE_ID": "456",
    "CI_JOB_ID": "1001",
}


@pytest.fixture
def toy_root(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/toy.py").write_text(
        'class Chooser:\n    def choose(self, flag):\n        if flag:\n            return "yes"\n        return "no"\n',
        encoding="utf-8",
    )
    (tmp_path / "run_toy.py").write_text(
        "import sys\nfrom pathlib import Path\nfrom src.toy import Chooser\n"
        'assert Chooser().choose(sys.argv[1] == "yes") in {"yes", "no"}\n'
        'if sys.argv[1] == "mutate":\n    with Path("src/toy.py").open("a") as out:\n        out.write("# changed during execution\\n")\n'
        'if sys.argv[1] == "fail":\n    sys.exit(7)\n',
        encoding="utf-8",
    )
    return tmp_path


def _invoke(
    root: Path, script: str, *arguments: str, hosted: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    for key in (*GITHUB_FIELDS, *GITLAB_FIELDS):
        environment.pop(key, None)
    environment.update(hosted or {})
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / script),
            "--root",
            str(root),
            "--source",
            "src",
            "--source-input",
            "src",
            "--source-input",
            "run_toy.py",
            *arguments,
        ],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


def _collect(
    root: Path, dialect: str, choice: str, hosted: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return _invoke(
        root,
        "collect_dialect_coverage.py",
        "--dialect",
        dialect,
        "--",
        sys.executable,
        "-m",
        "coverage",
        "run",
        "--branch",
        "--source",
        "src",
        "run_toy.py",
        choice,
        hosted=hosted,
    )


def _json(root: Path, name: str) -> dict:
    return json.loads((root / "var" / name).read_text(encoding="utf-8"))


def _passed(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.splitlines()[-1])["status"] == "PASS"


def _failed(result: subprocess.CompletedProcess[str], code: str) -> None:
    assert result.returncode != 0, result.stdout + result.stderr
    failure = json.loads(result.stdout.splitlines()[-1])
    assert failure["status"] == "FAIL"
    assert failure["error_code"] == code, failure


@pytest.fixture
def measured_pair(toy_root: Path) -> Path:
    _passed(_collect(toy_root, "sqlite", "yes"))
    _passed(_collect(toy_root, "postgresql", "no"))
    return toy_root


def test_native_union_updates_totals_lines_arcs_functions_and_classes(measured_pair: Path) -> None:
    primary = _json(measured_pair, "coverage.json")
    secondary = _json(measured_pair, "coverage-postgres.json")
    assert primary["totals"]["missing_branches"] == secondary["totals"]["missing_branches"] == 1
    assert same_subject(primary, secondary) is None
    _passed(_invoke(measured_pair, "merge_dialect_coverage.py"))
    merged = _json(measured_pair, "coverage-union.json")
    assert merged["totals"]["num_branches"] == 2
    assert merged["totals"]["covered_branches"] == 2
    assert merged["totals"]["percent_covered"] == 100
    file = merged["files"]["src/toy.py"]
    assert file["missing_lines"] == file["missing_branches"] == []
    assert file["executed_branches"] == [[3, 4], [3, 5]]
    assert file["executed_lines"] == [1, 2, 3, 4, 5]
    for region in (file["functions"]["Chooser.choose"], file["classes"]["Chooser"]):
        assert region["summary"]["percent_covered"] == 100
        assert region["summary"]["num_partial_branches"] == 0
        assert region["missing_branches"] == []
        assert region["executed_branches"] == [[3, 4], [3, 5]]
    assert (measured_pair / "var/coverage-union.data").is_file()
    assert (measured_pair / "var/coverage-sqlite.data").is_file()
    assert (measured_pair / "var/coverage-postgres.data").is_file()


def test_equal_statement_counts_and_lines_do_not_hide_different_arcs(toy_root: Path) -> None:
    source = toy_root / "src/toy.py"
    source.write_text(
        'class Chooser:\n    def choose(self, flag):\n        seen = 1\n        if flag:\n            return "yes"\n        return "no"\n',
        encoding="utf-8",
    )
    _passed(_collect(toy_root, "sqlite", "yes"))
    source.write_text(
        'class Chooser:\n    def choose(self, flag):\n        if flag:\n            seen = 1\n            return "yes"\n        return "no"\n',
        encoding="utf-8",
    )
    _passed(_collect(toy_root, "postgresql", "no"))
    primary, secondary = _json(toy_root, "coverage.json"), _json(toy_root, "coverage-postgres.json")
    first, second = primary["files"]["src/toy.py"], secondary["files"]["src/toy.py"]
    assert first["summary"]["num_statements"] == second["summary"]["num_statements"]
    assert set(first["executed_lines"] + first["missing_lines"]) == set(
        second["executed_lines"] + second["missing_lines"]
    )
    assert "branch arc universe" in (same_subject(primary, secondary) or "")
    _failed(_invoke(toy_root, "merge_dialect_coverage.py"), "SOURCE_MISMATCH")


def test_changed_source_during_a_successful_command_cannot_stamp_pass(toy_root: Path) -> None:
    _failed(_collect(toy_root, "sqlite", "mutate"), "SOURCE_CHANGED_DURING_EXECUTION")
    assert _json(toy_root, "coverage-sqlite-receipt.json")["status"] == "FAIL"


def test_failed_command_replaces_stale_pass_and_is_not_mergeable(measured_pair: Path) -> None:
    _failed(_collect(measured_pair, "sqlite", "fail"), "PRODUCER_FAILED")
    assert _json(measured_pair, "coverage-sqlite-receipt.json")["status"] == "FAIL"
    _failed(_invoke(measured_pair, "merge_dialect_coverage.py"), "PRODUCER_NOT_PASSED")


@pytest.mark.parametrize(
    "name",
    [
        "coverage.json",
        "coverage-sqlite.data",
        "coverage-sqlite-receipt.json",
        "coverage-postgres.json",
        "coverage-postgres.data",
        "coverage-postgres-receipt.json",
    ],
)
def test_every_required_input_is_fail_closed_and_stale_union_is_removed(
    measured_pair: Path, name: str
) -> None:
    _passed(_invoke(measured_pair, "merge_dialect_coverage.py"))
    (measured_pair / "var" / name).unlink()
    _failed(_invoke(measured_pair, "merge_dialect_coverage.py"), "MISSING_INPUT")
    assert not (measured_pair / "var/coverage-union.json").exists()
    assert not (measured_pair / "var/coverage-union.data").exists()


def test_raw_dataset_tampering_is_rejected(measured_pair: Path) -> None:
    with (measured_pair / "var/coverage-postgres.data").open("ab") as out:
        out.write(b"changed bytes")
    _failed(_invoke(measured_pair, "merge_dialect_coverage.py"), "ARTIFACT_MISMATCH")


def test_self_consistent_receipt_hash_cannot_hide_json_raw_disagreement(
    measured_pair: Path,
) -> None:
    path = measured_pair / "var/coverage-postgres.json"
    report = _json(measured_pair, path.name)
    report["files"]["src/toy.py"]["classes"]["Chooser"]["summary"]["percent_covered"] = 100
    path.write_text(json.dumps(report), encoding="utf-8")
    receipt_path = measured_pair / "var/coverage-postgres-receipt.json"
    receipt = _json(measured_pair, receipt_path.name)
    receipt["artifacts"]["report"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    _failed(_invoke(measured_pair, "merge_dialect_coverage.py"), "RAW_REPORT_MISMATCH")


def test_stale_source_with_the_same_line_and_branch_shape_is_rejected(measured_pair: Path) -> None:
    path = measured_pair / "src/toy.py"
    path.write_text(path.read_text(encoding="utf-8").replace('"yes"', '"YES"'), encoding="utf-8")
    _failed(_invoke(measured_pair, "merge_dialect_coverage.py"), "SOURCE_MISMATCH")


def test_receipt_for_the_wrong_dialect_is_rejected(measured_pair: Path) -> None:
    path = measured_pair / "var/coverage-postgres-receipt.json"
    receipt = _json(measured_pair, path.name)
    receipt["dialect"] = "sqlite"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    _failed(_invoke(measured_pair, "merge_dialect_coverage.py"), "DIALECT_MISMATCH")


def test_hosted_execution_requires_complete_identity(toy_root: Path) -> None:
    incomplete = {**HOSTED}
    incomplete.pop("GITHUB_RUN_ATTEMPT")
    _failed(_collect(toy_root, "sqlite", "yes", incomplete), "RUN_IDENTITY")
    _failed(_collect(toy_root, "sqlite", "yes", {"GITHUB_SHA": "a" * 40}), "RUN_IDENTITY")


def test_hosted_receipts_must_match_current_run_and_attempt(toy_root: Path) -> None:
    _passed(_collect(toy_root, "sqlite", "yes", HOSTED))
    _passed(_collect(toy_root, "postgresql", "no", HOSTED))
    _passed(_invoke(toy_root, "merge_dialect_coverage.py", hosted=HOSTED))
    for field, value in (
        ("GITHUB_RUN_ID", "124"),
        ("GITHUB_RUN_ATTEMPT", "2"),
        ("GITHUB_SHA", "b" * 40),
        ("GITHUB_REPOSITORY", "other/repository"),
    ):
        _failed(
            _invoke(toy_root, "merge_dialect_coverage.py", hosted={**HOSTED, field: value}),
            "RUN_MISMATCH",
        )
    _failed(_invoke(toy_root, "merge_dialect_coverage.py"), "RUN_MISMATCH")


def test_count_only_json_is_not_an_executable_universe() -> None:
    report = {"files": {"a.py": {"summary": {"num_statements": 10}, "missing_branches": []}}}
    assert same_subject(report, report) is not None


def test_receipts_from_different_actions_attempts_cannot_be_combined(toy_root: Path) -> None:
    _passed(_collect(toy_root, "sqlite", "yes", HOSTED))
    _passed(_collect(toy_root, "postgresql", "no", {**HOSTED, "GITHUB_RUN_ATTEMPT": "2"}))
    _failed(_invoke(toy_root, "merge_dialect_coverage.py", hosted=HOSTED), "RUN_MISMATCH")


def test_gitlab_pipeline_identity_allows_distinct_jobs_but_rejects_stale_pipeline(
    toy_root: Path,
) -> None:
    _passed(_collect(toy_root, "sqlite", "yes", GITLAB))
    _passed(_collect(toy_root, "postgresql", "no", {**GITLAB, "CI_JOB_ID": "1002"}))
    _passed(_invoke(toy_root, "merge_dialect_coverage.py", hosted={**GITLAB, "CI_JOB_ID": "1003"}))
    _failed(
        _invoke(toy_root, "merge_dialect_coverage.py", hosted={**GITLAB, "CI_PIPELINE_ID": "457"}),
        "RUN_MISMATCH",
    )
    _failed(_invoke(toy_root, "merge_dialect_coverage.py"), "RUN_MISMATCH")


def test_incomplete_gitlab_identity_cannot_fall_back_to_local(toy_root: Path) -> None:
    identity = {**GITLAB}
    identity.pop("CI_PIPELINE_ID")
    _failed(_collect(toy_root, "sqlite", "yes", identity), "RUN_IDENTITY")
