"""Real tiny campaigns calibrate release mutation evidence before the eight real mutants."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import run_release_mutation_microcampaign as micro
from scripts.mutation_probe_execution import run_suite
from scripts.release_mutation_summary import campaign_summary


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str):
    source = tmp_path / "apps/api/src/subject.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 1\n")
    test = tmp_path / "apps/api/tests/test_subject.py"
    test.parent.mkdir(parents=True)
    test.write_text(body)
    monkeypatch.setattr(micro, "ROOT", tmp_path)
    mutant = micro.Mutant(
        "CONTROL",
        "apps/api/src/subject.py",
        "value = 1",
        "value = 0",
        ("apps/api/tests/test_subject.py",),
        "measured control",
    )
    observed = []

    def execute(workspace: Path, tests: tuple[str, ...]):
        observed.append((workspace / mutant.path).read_text())
        return run_suite(2, workspace, test_paths=tests, stop_on_failure=False)

    monkeypatch.setattr(micro, "_execute", execute)
    return mutant, source, observed


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ("from subject import value\ndef test_value(): assert value == 1\n", "KILLED"),
        ("def test_value(): assert True\n", "SURVIVED"),
    ],
)
def test_actual_kill_and_survivor_have_baseline_and_exact_receipts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    body: str,
    status: str,
) -> None:
    mutant, source, observed = _fixture(tmp_path, monkeypatch, body)
    original = source.read_bytes()
    result = micro.run_mutant(mutant)
    assert result["status"] == status
    assert result["baseline"]["status"] == "PASSED"
    assert result["execution"]["tests"] == result["baseline"]["tests"] == 1
    assert observed == ["value = 1\n", "value = 0\n"]
    assert source.read_bytes() == original and result["source_unchanged"] is True
    assert result["source_sha256"] == hashlib.sha256(original).hexdigest()
    assert result["mutant_sha256"] == hashlib.sha256(b"value = 0\n").hexdigest()


@pytest.mark.parametrize(
    "body",
    [
        "def test_value(): assert False\n",
        "import missing_baseline_dependency\n",
        "# zero tests\n",
        "import pytest\ndef test_value(): pytest.skip('unmeasured')\n",
    ],
)
def test_failed_or_unmeasured_baseline_never_executes_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    body: str,
) -> None:
    mutant, source, observed = _fixture(tmp_path, monkeypatch, body)
    result = micro.run_mutant(mutant)
    assert result["status"] == "INVALID"
    assert result["reason"].startswith("BASELINE_")
    assert result["execution"] is None and result["test_exit_code"] is None
    assert observed == ["value = 1\n"] and source.read_text() == "value = 1\n"
    assert campaign_summary([result])["status"] == "FAIL"


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (
            "from subject import value\nif value == 0: import missing_mutant_dependency\n"
            "def test_value(): assert True\n",
            "PYTEST_EXIT_2",
        ),
        (
            "from subject import value\nimport pytest\n@pytest.fixture\ndef resource():\n"
            "    if value == 0: raise RuntimeError('setup failed')\n"
            "def test_value(resource): assert True\n",
            "PYTEST_ERRORS",
        ),
        (
            "from subject import value\nimport time\ndef test_value():\n"
            "    if value == 0: time.sleep(30)\n    assert True\n",
            "TIMEOUT:",
        ),
        (
            "from subject import value\nif value == 1:\n    def test_value(): assert True\n",
            "PYTEST_EXIT_5",
        ),
        (
            "from subject import value\nimport pytest\ndef test_first(): assert True\n"
            "def test_value():\n    if value == 0: pytest.skip('hidden')\n"
            "    assert True\n",
            "NEW_SKIPPED_TESTS",
        ),
        (
            "from subject import value\nif value == 1:\n"
            "    def test_disappears(): assert True\n"
            "def test_value(): assert value == 1\n",
            "MISSING_TEST_IDENTITIES",
        ),
        (
            "from subject import value\nif value == 0:\n"
            "    def test_appears(): assert True\n"
            "def test_value(): assert value == 1\n",
            "UNEXPECTED_TEST_IDENTITIES",
        ),
        (
            "from subject import value\nimport pytest\ndef test_value(): assert value == 1\n"
            "def test_skip_changed():\n    if value == 1: pytest.skip('baseline skip')\n"
            "    assert True\n",
            "CHANGED_TEST_EXECUTION",
        ),
    ],
)
def test_invalid_execution_cannot_be_credited_as_killed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    body: str,
    reason: str,
) -> None:
    mutant, source, observed = _fixture(tmp_path, monkeypatch, body)
    result = micro.run_mutant(mutant)
    assert result["status"] == "INVALID", result
    assert result["reason"].startswith(reason), result
    assert result["baseline"]["status"] == "PASSED"
    assert observed == ["value = 1\n", "value = 0\n"]
    assert source.read_text() == "value = 1\n"
    summary = campaign_summary([result])
    assert summary["status"] == "FAIL" and summary["invalid"] == ["CONTROL"]
    assert summary["mutants"] == 1 and summary["killed"] == 0


def test_baseline_source_drift_is_not_a_mutation_measurement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = (
        "from pathlib import Path\ndef test_value():\n"
        "    Path('apps/api/src/subject.py').write_text('value = 7\\n')\n"
        "    assert True\n"
    )
    mutant, source, observed = _fixture(tmp_path, monkeypatch, body)
    result = micro.run_mutant(mutant)
    assert result["status"] == "INVALID" and result["reason"] == "BASELINE_CHANGED_SOURCE"
    assert result["baseline"]["status"] == "PASSED" and result["execution"] is None
    assert observed == ["value = 1\n"] and source.read_text() == "value = 1\n"


def test_empty_selection_never_expands_into_default_suite(tmp_path: Path) -> None:
    result = run_suite(2, tmp_path, test_paths=(), stop_on_failure=False)
    assert result.status == "INCONCLUSIVE" and result.reason == "NO_SELECTED_TESTS"


def test_empty_actual_cli_campaign_cannot_publish_pass(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "empty.json"
    monkeypatch.setattr(micro, "MUTANTS", ())
    monkeypatch.setattr(micro.sys, "argv", ["microcampaign", "--out", str(output)])
    assert micro.main() == 1
    report = json.loads(output.read_text())
    assert report["status"] == "FAIL" and report["mutants"] == report["killed"] == 0


def test_unknown_outcome_is_preserved_as_invalid_not_removed_from_denominator() -> None:
    results = [{"id": "one", "status": "KILLED"}, {"id": "two", "status": "UNKNOWN"}]
    summary = campaign_summary(results)
    assert summary == {
        "mutants": 2,
        "killed": 1,
        "survived": [],
        "invalid": ["two"],
        "status": "FAIL",
    }


def test_existing_stream_tail_fields_remain_actual_separate_streams(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mutant, _source, _observed = _fixture(
        tmp_path,
        monkeypatch,
        "import sys\ndef test_value():\n    print('stdout-marker')\n"
        "    print('stderr-marker', file=sys.stderr)\n    assert True\n",
    )
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = -s\n")
    result = micro.run_mutant(mutant)
    assert result["status"] == "SURVIVED"
    assert "stdout-marker" in result["stdout_tail"] and "stderr-marker" not in result["stdout_tail"]
    assert "stderr-marker" in result["stderr_tail"] and "stdout-marker" not in result["stderr_tail"]
