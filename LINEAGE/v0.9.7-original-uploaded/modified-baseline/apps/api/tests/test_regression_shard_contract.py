import importlib.util
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[3] / "scripts" / "run_regression_shards.py"
    spec = importlib.util.spec_from_file_location("regression_shards", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_regression_bucket_is_deterministic_and_partitioned() -> None:
    module = _module()
    nodeids = [f"apps/api/tests/test_x.py::test_{i}" for i in range(100)]
    shards = [[n for n in nodeids if module.bucket(n, 7) == i] for i in range(7)]
    assert sorted(n for shard in shards for n in shard) == sorted(nodeids)
    assert len({n for shard in shards for n in shard}) == len(nodeids)
    assert [module.bucket(n, 7) for n in nodeids] == [module.bucket(n, 7) for n in nodeids]


def test_bounded_runner_kills_the_entire_process_group_on_timeout(tmp_path) -> None:
    module = _module()
    import os
    import signal
    import sys
    import time

    if os.name != "posix":
        return
    pid_file = tmp_path / "child.pid"
    code = (
        "import pathlib, subprocess, sys, time; "
        "p=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid)); "
        "time.sleep(30)"
    )
    exit_code, _stdout, _stderr, timed_out, termination = module.run_bounded(
        [sys.executable, "-c", code], cwd=module.ROOT, env=module._env(), timeout_seconds=2.0
    )
    assert timed_out is True
    assert exit_code is None
    assert termination in {"sigterm_process_group", "sigkill_process_group"}
    child_pid = int(pid_file.read_text())
    for _ in range(20):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        os.kill(child_pid, signal.SIGKILL)
        raise AssertionError("timeout left a child process alive")


def test_bounded_runner_kills_descendant_after_parent_exits(tmp_path) -> None:
    module = _module()
    import os
    import signal
    import sys
    import time

    if os.name != "posix":
        return
    pid_file = tmp_path / "orphan.pid"
    # Child inherits the pipe; parent exits immediately. communicate() must still
    # time out and reap the entire process group rather than trusting parent.poll().
    code = (
        "import pathlib, subprocess, sys; "
        "p=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid))"
    )
    exit_code, _stdout, _stderr, timed_out, termination = module.run_bounded(
        [sys.executable, "-c", code], cwd=module.ROOT, env=module._env(), timeout_seconds=2.0
    )
    assert timed_out is True
    assert exit_code is None
    assert termination in {"sigterm_process_group", "sigkill_process_group"}
    child_pid = int(pid_file.read_text())
    for _ in range(20):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        os.kill(child_pid, signal.SIGKILL)
        raise AssertionError("exited parent left a descendant process alive")


def test_bounded_runner_sigkills_descendant_that_ignores_sigterm(tmp_path) -> None:
    module = _module()
    import os
    import signal
    import sys
    import time

    if os.name != "posix":
        return
    pid_file = tmp_path / "stubborn.pid"
    child = (
        "import signal,time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "time.sleep(30)"
    )
    code = (
        "import pathlib,subprocess,sys; "
        f"p=subprocess.Popen([sys.executable, '-c', {child!r}]); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid))"
    )
    started = time.monotonic()
    exit_code, _stdout, _stderr, timed_out, termination = module.run_bounded(
        [sys.executable, "-c", code], cwd=module.ROOT, env=module._env(), timeout_seconds=2.0
    )
    assert time.monotonic() - started < 7.0
    assert timed_out is True
    assert exit_code is None
    assert termination == "sigkill_process_group"
    child_pid = int(pid_file.read_text())
    for _ in range(20):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        os.kill(child_pid, signal.SIGKILL)
        raise AssertionError("SIGTERM-ignoring descendant survived bounded execution")


def _receipt(*, release_tag: str = "v0.9.7", shard_index: int = 0) -> dict[str, object]:
    return {
        "release_tag": release_tag,
        "source_digest": "a" * 64,
        "collection_digest": "b" * 64,
        "shard_index": shard_index,
        "shard_count": 2,
        "pytest_args": [],
        "selected_nodeids": [f"tests/test_x.py::test_{shard_index}"],
        "collection_count": 2,
        "status": "PASS",
        "junit": {"tests": 1, "failures": 0, "errors": 0, "skipped": 0},
    }


def test_merge_identity_rejects_mixed_release_tags() -> None:
    module = _module()
    _identity, failures = module._receipt_identity([
        _receipt(release_tag="v0.9.7", shard_index=0),
        _receipt(release_tag="v0.9.6", shard_index=1),
    ])
    assert "release_tag_mismatch" in failures


def test_merge_identity_carries_exact_release_tag() -> None:
    module = _module()
    identity, failures = module._receipt_identity([
        _receipt(shard_index=0),
        _receipt(shard_index=1),
    ])
    assert failures == []
    assert identity["release_tag"] == "v0.9.7"


def test_collection_manifest_rejects_source_drift(tmp_path) -> None:
    module = _module()
    from regression_collection import build_manifest, load_verified_manifest
    payload = build_manifest(
        nodeids=["tests/test_x.py::test_a"],
        release_tag="v0.9.7",
        source_digest="a" * 64,
        pytest_args=[],
        python_version="3.12.13",
    )
    path = tmp_path / "collection.json"
    import json
    path.write_text(json.dumps(payload), encoding="utf-8")
    import pytest
    with pytest.raises(RuntimeError, match="source_digest"):
        load_verified_manifest(path, release_tag="v0.9.7", source_digest="b" * 64, pytest_args=[])


def test_collection_manifest_rejects_nodeid_tampering(tmp_path) -> None:
    _module()
    from regression_collection import build_manifest, load_verified_manifest
    payload = build_manifest(
        nodeids=["tests/test_x.py::test_a"],
        release_tag="v0.9.7",
        source_digest="a" * 64,
        pytest_args=[],
        python_version="3.12.13",
    )
    payload["nodeids"].append("tests/test_x.py::test_tampered")
    path = tmp_path / "collection.json"
    import json
    path.write_text(json.dumps(payload), encoding="utf-8")
    import pytest
    with pytest.raises(RuntimeError, match="collection_count|collection_digest"):
        load_verified_manifest(path, release_tag="v0.9.7", source_digest="a" * 64, pytest_args=[])
