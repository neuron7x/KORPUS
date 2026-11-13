"""Actual tiny pytest campaigns exercise both consumers of the bounded runner."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts import process_tree_runtime as runtime
from scripts import run_mutation_tests as native
from scripts.mutation_probe_execution import run_suite


@pytest.mark.parametrize(
    ("test", "expected", "reason"),
    [
        ("def test_value(): assert True\n", "SURVIVED", None),
        ("from subject import value\ndef test_value(): assert value == 1\n", "KILLED", None),
        ("import missing_boundary_dependency\n", "ERROR", "pytest_exit_2"),
        ("import time\ndef test_value(): time.sleep(30)\n", "ERROR", "pytest_timeout"),
        (
            "import os\ndef test_value():\n    while True: os.write(1, b'x'*65536)\n",
            "ERROR",
            "execution_inconclusive",
        ),
    ],
)
def test_native_mutation_runner_uses_actual_bounded_verdict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    test: str,
    expected: str,
    reason: str | None,
) -> None:
    source = tmp_path / "src"
    source.mkdir()
    subject = source / "subject.py"
    subject.write_text("value = 1\n")
    test_path = tmp_path / "test_subject.py"
    test_path.write_text(test)
    monkeypatch.setattr(
        native, "_prepare_mutant_sandbox", lambda *_args: (subject, source, tmp_path, True)
    )

    def bounded(command, **kwargs):
        # Disable pytest's own capture so the output-control case reaches OS pipes.
        return runtime.execute_bounded_process(
            [*command, "-s", "--no-cov"], **{**kwargs, "timeout_seconds": 2}
        )

    monkeypatch.setattr(native, "run_bounded", bounded)
    mutant = native.Mutant("CONTROL", "subject.py", "value = 1", "value = 0", (str(test_path),))
    result = native.run_mutant(mutant)
    assert result["status"] == expected, result
    if expected == "ERROR":
        assert "returncode" not in result or result["returncode"] != 1
        assert result["reason"] == reason


def test_measured_pytest_baseline_does_not_hide_output_overflow(tmp_path: Path) -> None:
    tests = tmp_path / "apps/api/tests"
    tests.mkdir(parents=True)
    # Send bytes to the runner's pipes, not pytest's independent capture files.
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = -s\n")
    (tests / "test_subject.py").write_text(
        "import os\nwhile True: os.write(2, b'x'*65536)\ndef test_value(): assert True\n"
    )
    result = run_suite(3, tmp_path)
    assert result.status == "INCONCLUSIVE"
    assert result.returncode is None
    assert result.reason.startswith("EXECUTION:output_limit:")


def test_signal_exit_waits_for_supervisor_cleanup_before_source_restore(tmp_path: Path) -> None:
    import subprocess
    import time

    scripts = Path(runtime.__file__).parent
    marker = tmp_path / "child.json"
    restored = tmp_path / "restored"
    payload = (
        "import os,pathlib,time; "
        "s=pathlib.Path('/proc/self/stat').read_text().split(') ',1)[1].split(); "
        f"pathlib.Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(30)"
    )
    caller = (
        "import os,signal,sys\nfrom pathlib import Path\n"
        f"sys.path.insert(0,{str(scripts)!r})\n"
        "from bounded_process import run_bounded\n"
        "def stop(*_args): raise SystemExit(42)\n"
        "signal.signal(signal.SIGTERM,stop)\n"
        "try:\n"
        f"    run_bounded([sys.executable,'-c',{payload!r}],cwd=Path.cwd(),env=dict(os.environ),timeout_seconds=30)\n"
        "finally:\n"
        f"    Path({str(restored)!r}).write_text('restored')\n"
    )
    with subprocess.Popen([sys.executable, "-c", caller], cwd=tmp_path) as process:
        for _ in range(100):
            if marker.exists():
                break
            time.sleep(0.01)
        assert marker.exists()
        process.terminate()
        assert process.wait(timeout=5) == 42
    assert restored.read_text() == "restored"
    assert not Path(f"/proc/{marker.read_text()}").exists()


def test_native_baseline_unknown_prevents_mutant_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "unsupported")

    def forbidden(*_args):
        pytest.fail("baseline without measured execution authorized a mutant")

    monkeypatch.setattr(native, "run_mutant", forbidden)
    mutant = native.Mutant("CONTROL", "unused.py", "one", "two", ("unused_test.py",))
    with pytest.raises(RuntimeError, match=r"execution inconclusive.*unsupported_child_ownership"):
        native.run_selected([mutant], 1)


@pytest.mark.parametrize(
    ("mode", "expected"), [("pass", "PASS"), ("fail", "FAIL"), ("unsupported", "UNKNOWN")]
)
def test_regression_receipt_keeps_unmeasured_execution_distinct(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected: str,
) -> None:
    import argparse
    import json

    from scripts import run_regression_shards as regression

    subject = tmp_path / "test_subject.py"
    subject.write_text("def test_subject(): assert " + str(mode != "fail") + "\n")
    monkeypatch.setattr(regression, "ROOT", tmp_path)
    monkeypatch.setattr(regression, "compute_source_digest", lambda _root: "a" * 64)
    monkeypatch.setattr(regression, "release_tag", lambda _root: "test-fixture")
    monkeypatch.setattr(regression, "collect_nodeids", lambda _args: [str(subject)])
    if mode == "unsupported":
        monkeypatch.setattr(sys, "platform", "unsupported")
    args = argparse.Namespace(
        collection_manifest=None,
        pytest_args=[],
        shard_count=1,
        shard_index=0,
        out=tmp_path / "receipt.json",
        timeout_seconds=3,
    )
    code = regression.run_shard(args)
    receipt = json.loads(args.out.read_text())
    assert receipt["status"] == expected
    assert code == (0 if expected == "PASS" else 1)
    if expected == "UNKNOWN":
        assert receipt["exit_code"] is None
        assert receipt["termination"] == "unsupported_child_ownership"
