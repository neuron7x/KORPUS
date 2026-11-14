"""Real tiny pytest processes discriminate instrument failures from measured mutations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from scripts import probe_uncatalogued_mutation as probe


def _workspace(root: Path, test_source: str) -> Path:
    tests = root / "apps/api/tests"
    tests.mkdir(parents=True)
    (tests / "test_subject.py").write_text(test_source, encoding="utf-8")
    source = root / "apps/api/src"
    source.mkdir(parents=True)
    (source / "subject.py").write_text("def eligible(value):\n    return value == 1\n")
    return root


@pytest.mark.parametrize(
    ("source", "status", "reason"),
    [
        ("def test_subject(): assert True\n", "PASSED", "COMPLETED"),
        ("def test_subject(): assert False\n", "FAILED", "TEST_FAILURE"),
        ("# no tests\n", "INCONCLUSIVE", "PYTEST_EXIT_5"),
        ("import absent_probe_dependency\n", "INCONCLUSIVE", "PYTEST_EXIT_2"),
        (
            "import pytest\n@pytest.fixture\ndef broken(): raise RuntimeError('fixture')\n"
            "def test_subject(broken): assert True\n",
            "INCONCLUSIVE",
            "PYTEST_ERRORS",
        ),
        (
            "import pytest\ndef test_subject(): pytest.skip('no execution')\n",
            "INCONCLUSIVE",
            "NO_EXECUTED_TESTS",
        ),
    ],
)
def test_actual_pytest_outcomes_are_not_interchangeable(
    tmp_path: Path, source: str, status: str, reason: str
) -> None:
    result = probe.suite_kills(15, _workspace(tmp_path, source))
    assert (result.status, result.reason) == (status, reason)


def test_actual_timeout_is_inconclusive(tmp_path: Path) -> None:
    root = _workspace(tmp_path, "import time\ndef test_subject(): time.sleep(30)\n")
    result = probe.suite_kills(1, root)
    assert result.status == "INCONCLUSIVE"
    assert result.reason.startswith("TIMEOUT:")
    assert result.returncode is None


def _run_probe(
    root: Path, monkeypatch: pytest.MonkeyPatch, timeout: float = 15
) -> tuple[int, dict]:
    monkeypatch.setattr(probe, "uncatalogued_modules", lambda _paths: ["apps/api/src/subject.py"])
    args = argparse.Namespace(
        paths=None, sample=1, seed=7, timeout=timeout, out=root / "report.json"
    )
    original = (root / "apps/api/src/subject.py").read_bytes()
    code = probe.probe(args, root)
    assert (root / "apps/api/src/subject.py").read_bytes() == original
    return code, json.loads(args.out.read_text())


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from subject import eligible\ndef test_subject(): assert eligible(1)\n", "KILLED"),
        ("def test_subject(): assert True\n", "SURVIVED"),
    ],
)
def test_full_probe_requires_baseline_and_distinguishes_real_survival(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str, expected: str
) -> None:
    code, report = _run_probe(_workspace(tmp_path, source), monkeypatch)
    assert code == 0
    assert report["status"] == "COMPLETE"
    assert report["baseline"]["status"] == "PASSED"
    assert report["results"][0]["status"] == expected
    assert report["kill_rate"] == (1.0 if expected == "KILLED" else 0.0)
    assert report["sampled"] == report["executed"] == 1
    assert report["inconclusive"] == report["unexecuted"] == 0


def test_failed_unmodified_baseline_prevents_all_mutations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, "def test_subject(): assert False\n")

    def unexpected_mutation(*_args: object) -> str:
        pytest.fail("a failing baseline authorized a mutation")

    monkeypatch.setattr(probe, "apply", unexpected_mutation)
    code, report = _run_probe(root, monkeypatch)
    assert code != 0
    assert report["status"] == "BASELINE_FAILED"
    assert report["baseline"]["status"] == "FAILED"
    assert report["executed"] == report["killed"] == report["survived"] == 0
    assert report["unexecuted"] == report["sampled"] == 1
    assert report["kill_rate"] is report["kill_rate_interval_95"] is None


def test_no_eligible_mutation_is_not_a_completed_measurement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path, "def test_subject(): assert True\n")
    (root / "apps/api/src/subject.py").write_text("answer = 1\n")

    def unexpected_execution(*_args: object) -> None:
        pytest.fail("empty sample launched pytest")

    monkeypatch.setattr(probe, "suite_kills", unexpected_execution)
    code, report = _run_probe(root, monkeypatch)
    assert code != 0
    assert report["status"] == "NOT_MEASURED"
    assert report["sampled"] == report["executed"] == 0
    assert report["baseline"] is report["kill_rate"] is None


def test_skipping_the_affected_test_cannot_create_a_survivor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(
        tmp_path,
        "import pytest\nfrom subject import eligible\n"
        "def test_first(): assert True\n"
        "def test_subject():\n    if not eligible(1): pytest.skip('masked')\n"
        "    assert eligible(1)\n",
    )
    code, report = _run_probe(root, monkeypatch)
    assert code != 0
    assert report["status"] == "INCONCLUSIVE"
    assert report["inconclusive"] == report["sampled"] == 1
    assert report["results"][0]["reason"] == "NEW_SKIPPED_TESTS"
    assert report["survived"] == report["killed"] == 0
    assert report["kill_rate"] is report["kill_rate_interval_95"] is None


def test_incomplete_sample_does_not_shrink_the_denominator(tmp_path: Path) -> None:
    baseline = probe.SuiteExecution("PASSED", "COMPLETED", 1, 0, ("test::subject",))
    plan = probe.ProbePlan(1, 2, 2, 7, baseline)
    args = argparse.Namespace(out=tmp_path / "report.json")
    rows = [{"status": "KILLED"}, {"status": "INCONCLUSIVE", "reason": "TIMEOUT"}]
    assert probe._publish(args, plan, rows) != 0
    report = json.loads(args.out.read_text())
    assert report["sampled"] == report["executed"] == 2
    assert report["killed"] == report["inconclusive"] == 1
    assert report["survived"] == 0
    assert report["kill_rate"] is report["kill_rate_interval_95"] is None


def test_measurement_restores_exact_source_bytes_and_records_both_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib

    root = _workspace(
        tmp_path, "from subject import eligible\ndef test_subject(): assert eligible(1)\n"
    )
    original = b"def eligible(value):\r\n    return value == 1\r\n"
    (root / "apps/api/src/subject.py").write_bytes(original)
    code, report = _run_probe(root, monkeypatch)
    assert code == 0
    row = report["results"][0]
    assert row["source_sha256"] == hashlib.sha256(original).hexdigest()
    assert row["mutant_sha256"] == hashlib.sha256(original.replace(b"==", b"!=")).hexdigest()


@pytest.mark.parametrize(
    ("test_source", "reason"),
    [
        (
            "import time\nfrom subject import eligible\n"
            "def test_subject():\n    if not eligible(1): time.sleep(30)\n"
            "    assert eligible(1)\n",
            "TIMEOUT:",
        ),
        (
            "import pytest\nfrom subject import eligible\n@pytest.fixture\n"
            "def subject():\n    if not eligible(1): raise RuntimeError('setup')\n"
            "    return True\ndef test_subject(subject): assert subject\n",
            "PYTEST_ERRORS",
        ),
        (
            "from subject import eligible\n"
            "if not eligible(1): import absent_probe_dependency\n"
            "def test_subject(): assert True\n",
            "PYTEST_EXIT_2",
        ),
    ],
)
def test_execution_failure_after_a_passing_baseline_never_counts_as_a_kill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, test_source: str, reason: str
) -> None:
    code, report = _run_probe(_workspace(tmp_path, test_source), monkeypatch, timeout=5)
    assert code != 0
    assert report["baseline"]["status"] == "PASSED"
    assert report["status"] == "INCONCLUSIVE"
    assert report["results"][0]["reason"].startswith(reason)
    assert report["sampled"] == report["executed"] == report["inconclusive"] == 1
    assert report["killed"] == report["survived"] == 0
    assert report["kill_rate"] is report["kill_rate_interval_95"] is None
