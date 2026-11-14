"""Real process controls: no completed receipt while an owned descendant survives."""

from __future__ import annotations

import ctypes
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts import process_supervisor_client as client
from scripts import process_tree_runtime as runtime

SCRIPTS = Path(runtime.__file__).parent


def _stat(pid: int) -> list[str]:
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1].split()
    except FileNotFoundError:
        return []


def _record(marker: Path) -> str:
    return (
        "import json,os,pathlib; "
        "s=pathlib.Path('/proc/self/stat').read_text().split(') ',1)[1].split(); "
        f"f=open({str(marker)!r},'a'); f.write(json.dumps([os.getpid(),s[19]])+'\\n'); f.close(); "
    )


def _assert_reaped(marker: Path) -> None:
    identities = [json.loads(line) for line in marker.read_text().splitlines()]
    assert identities
    remaining = []
    for pid, start in identities:
        state = _stat(pid)
        if state and state[19] == start:
            remaining.append((pid, state[0]))
            # Failure cleanup is restricted to the exact fixture's pinned identity.
            libc = ctypes.CDLL(None, use_errno=True)
            fd = libc.pidfd_open(pid, 0)
            assert fd >= 0
            try:
                libc.pidfd_send_signal(fd, signal.SIGKILL, None, 0)
            finally:
                os.close(fd)
    assert not remaining, f"owned children were not reaped: {remaining}"


def _run(code: str, tmp_path: Path, timeout: float = 0.4) -> client.BoundedResult:
    return runtime.execute_bounded_process(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=dict(os.environ),
        timeout_seconds=timeout,
    )


@pytest.mark.parametrize("detached", [False, True])
@pytest.mark.parametrize("close_output", [False, True])
def test_root_exit_is_not_completion_with_surviving_child(
    tmp_path: Path,
    detached: bool,
    close_output: bool,
) -> None:
    marker = tmp_path / "children.jsonl"
    child = _record(marker) + "import time; time.sleep(30)"
    streams = ",stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL" if close_output else ""
    code = (
        "import subprocess,sys; "
        f"subprocess.Popen([sys.executable,'-c',{child!r}],start_new_session={detached}{streams})"
    )
    result = _run(code, tmp_path)
    _assert_reaped(marker)
    assert result[0] is None and result[3] is True
    assert result[4] in {"sigterm_descendants", "sigkill_descendants"}


def test_setsid_double_fork_and_closed_pipes_are_still_owned(tmp_path: Path) -> None:
    marker = tmp_path / "children.jsonl"
    child = (
        "import os,time\n"
        "if os.fork(): os._exit(0)\n"
        "os.setsid()\n"
        "if os.fork(): os._exit(0)\n"
        + _record(marker)
        + "os.close(1); os.close(2); time.sleep(30)\n"
    )
    result = _run(child, tmp_path)
    _assert_reaped(marker)
    assert result[0] is None and result[3] is True


def test_cleanup_adopts_grandchildren_born_in_sigterm_handler(tmp_path: Path) -> None:
    marker = tmp_path / "children.jsonl"
    code = (
        "import os,signal,time\n"
        "def terminate(_signum,_frame):\n"
        "    import os\n"
        "    signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
        "    if os.fork(): os._exit(0)\n"
        "    os.setsid()\n"
        "    " + _record(marker) + "time.sleep(30); os._exit(0)\n"
        "signal.signal(signal.SIGTERM,terminate)\n" + _record(marker) + "time.sleep(30)\n"
    )
    started = time.monotonic()
    result = _run(code, tmp_path)
    assert time.monotonic() - started < 5
    _assert_reaped(marker)
    assert len(marker.read_text().splitlines()) == 2, result
    assert result[0] is None and result[3] is True
    assert result[4] == "sigkill_descendants"


@pytest.mark.parametrize("stream", [1, 2])
def test_output_overflow_is_bounded_and_never_a_test_kill(tmp_path: Path, stream: int) -> None:
    result = _run(f"import os\nwhile True: os.write({stream}, b'x'*65536)\n", tmp_path, 2)
    assert result[0] is None and result[3] is False
    assert result[4].startswith("output_limit:")
    assert len(result[stream]) == client.OUTPUT_LIMIT_BYTES
    assert max(len(result[1]), len(result[2])) <= client.OUTPUT_LIMIT_BYTES


@pytest.mark.parametrize("code", [0, 1, 7])
def test_completed_exit_and_both_streams_are_preserved(tmp_path: Path, code: int) -> None:
    result = _run(
        f"import sys; print('out'); print('err',file=sys.stderr); sys.exit({code})",
        tmp_path,
    )
    assert result == (code, "out\n", "err\n", False, "not_required")


def test_parent_subreaper_and_unrelated_process_are_unchanged(tmp_path: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    before, after = ctypes.c_int(), ctypes.c_int()
    assert libc.prctl(37, ctypes.byref(before), 0, 0, 0) == 0
    with subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"]) as unrelated:
        try:
            assert _run("import time; time.sleep(30)", tmp_path)[3] is True
            assert unrelated.poll() is None
            assert libc.prctl(37, ctypes.byref(after), 0, 0, 0) == 0
            assert after.value == before.value
        finally:
            unrelated.terminate()
            unrelated.wait(timeout=3)


def test_supervisor_failure_is_not_an_execution_result(tmp_path: Path) -> None:
    with subprocess.Popen(
        [sys.executable, "-c", "raise SystemExit(17)"],
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    ) as process:
        result = client._communicate(process, "{}", 1)
    assert result == (None, "", "", False, "supervisor_failed:cleanup_unproven")


@pytest.mark.parametrize("feature", ["prctl", "pidfd_open", "pidfd_send_signal"])
def test_unsupported_ownership_does_not_start_payload(tmp_path: Path, feature: str) -> None:
    marker = tmp_path / "unexpected"
    bootstrap = (
        "import ctypes,sys\n"
        f"sys.path.insert(0,{str(SCRIPTS)!r})\n"
        "import process_tree_supervisor as supervisor\n"
        "original=ctypes.CDLL\n"
        "class MissingCapability:\n"
        "    def __init__(self,*args,**kwargs): self.libc=original(*args,**kwargs)\n"
        "    def __getattr__(self,name):\n"
        f"        if name=={feature!r}: raise AttributeError(name)\n"
        "        return getattr(self.libc,name)\n"
        "ctypes.CDLL=MissingCapability\n"
        "supervisor.main()\n"
    )
    request = {
        "cmd": [sys.executable, "-c", f"open({str(marker)!r},'w').close()"],
        "cwd": str(tmp_path),
        "env": dict(os.environ),
        "timeout": 1,
    }
    run = subprocess.run(
        [sys.executable, "-c", bootstrap],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        timeout=3,
        check=False,
    )
    assert run.returncode == 0
    receipt = json.loads(run.stdout)
    assert receipt["returncode"] is None and receipt["children_reaped"] is False
    assert receipt["termination"] == "unsupported_child_ownership"
    assert not marker.exists()


def test_unsupported_platform_cannot_launch_payload(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(client.sys, "platform", "unsupported")
    marker = tmp_path / "unexpected"
    result = _run(f"open({str(marker)!r},'w').close()", tmp_path)
    assert result == (None, "", "", False, "unsupported_child_ownership")
    assert not marker.exists()


@pytest.mark.parametrize("clean", [False, None, "true", 1])
def test_unproved_cleanup_cannot_authorize_returncode(clean: object) -> None:
    result = client._receipt(
        {
            "returncode": 0,
            "children_reaped": clean,
            "stdout": "",
            "stderr": "",
            "timed_out": False,
            "termination": "not_required",
        }
    )
    assert result[0] is None
    assert "cleanup_unproven" in result[4]


def test_supervisor_cancellation_cleans_owned_descendant(tmp_path: Path) -> None:
    marker = tmp_path / "children.jsonl"
    child = _record(marker) + "import time; time.sleep(30)"
    command = (
        "import subprocess,sys; "
        + f"subprocess.Popen([sys.executable,'-c',{child!r}],start_new_session=True)"
    )
    request = {
        "cmd": [sys.executable, "-c", command],
        "cwd": str(tmp_path),
        "env": dict(os.environ),
        "timeout": 30,
    }
    with subprocess.Popen(
        [sys.executable, "-B", "-I", str(SCRIPTS / "process_tree_supervisor.py")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    ) as process:
        assert process.stdin is not None
        process.stdin.write(json.dumps(request))
        process.stdin.close()
        process.stdin = None
        for _ in range(100):
            if marker.exists():
                break
            time.sleep(0.01)
        process.terminate()
        stdout, _stderr = process.communicate(timeout=4)
    _assert_reaped(marker)
    receipt = json.loads(stdout)
    assert receipt["returncode"] is None and receipt["children_reaped"] is True
    assert receipt["termination"].startswith("cancelled:")


def test_naturally_exited_detached_child_is_reaped_before_success(tmp_path: Path) -> None:
    marker = tmp_path / "children.jsonl"
    child = _record(marker) + "import time; time.sleep(.1); print('child completed')"
    code = "import subprocess,sys; " + (
        f"subprocess.Popen([sys.executable,'-c',{child!r}],start_new_session=True)"
    )
    result = _run(code, tmp_path, 2)
    _assert_reaped(marker)
    assert result == (0, "child completed\n", "", False, "not_required")


def test_withheld_echild_proof_remains_bounded_and_inconclusive(tmp_path: Path) -> None:
    marker = tmp_path / "children.jsonl"
    bootstrap = (
        "import sys\n"
        f"sys.path.insert(0,{str(SCRIPTS)!r})\n"
        "import process_tree_supervisor as supervisor\n"
        "original=supervisor.ChildOwner.reap\n"
        "def without_completion_proof(self,pid):\n"
        "    original(self,pid)\n"
        "    return False\n"
        "supervisor.ChildOwner.reap=without_completion_proof\n"
        "supervisor.main()\n"
    )
    request = {
        "cmd": [sys.executable, "-c", _record(marker)],
        "cwd": str(tmp_path),
        "env": dict(os.environ),
        "timeout": 0.1,
    }
    started = time.monotonic()
    run = subprocess.run(
        [sys.executable, "-c", bootstrap],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        timeout=4,
        check=False,
    )
    assert time.monotonic() - started < 4
    _assert_reaped(marker)
    receipt = json.loads(run.stdout)
    assert receipt["returncode"] is None and receipt["children_reaped"] is False
    assert receipt["termination"] == "cleanup_unproven"
    assert client._receipt(receipt)[0] is None
