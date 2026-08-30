#!/usr/bin/env python3
"""Run one unattended agent against a disposable, repository-locked worktree."""

from __future__ import annotations

import argparse
import ctypes
import fcntl
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import IO

BUSY_EXIT = 75
DIRTY_EXIT = 76
TIMEOUT_EXIT = 124
PR_SET_CHILD_SUBREAPER = 36


class RepositoryBusy(RuntimeError):
    """Another unattended routine owns the repository-wide agent lease."""


class DirtyRepository(RuntimeError):
    """The source tree has changes that HEAD would silently omit."""


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def repository_lock_path(repository: Path) -> Path:
    common_dir = Path(_git(repository, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    return common_dir / "korpus-routine.lock"


@contextmanager
def repository_lease(repository: Path) -> Iterator[IO[str]]:
    lock_path = repository_lock_path(repository)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RepositoryBusy(f"repository lease is held: {lock_path}") from error
        lock.seek(0)
        lock.truncate()
        lock.write(f"pid={os.getpid()} started={time.time_ns()}\n")
        lock.flush()
        try:
            yield lock
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _write_receipt(state_dir: Path, name: str, receipt: dict[str, object]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    history = state_dir / f"{name}.jsonl"
    with history.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n")
    latest = state_dir / f"{name}.json"
    temporary = latest.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(latest)


def _provision_interpreter(repository: Path, worktree: Path) -> None:
    source = repository / "apps/api/.venv"
    destination = worktree / "apps/api/.venv"
    if source.is_dir() and not destination.exists():
        destination.symlink_to(source, target_is_directory=True)


def _remove_worktree(repository: Path, worktree: Path) -> None:
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree)],
        cwd=repository,
        check=False,
        capture_output=True,
    )
    subprocess.run(
        ["git", "worktree", "prune"],
        cwd=repository,
        check=False,
        capture_output=True,
    )


def _become_child_subreaper() -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def _descendant_pids(root_pid: int) -> set[int]:
    children: dict[int, set[int]] = {}
    for status in Path("/proc").glob("[0-9]*/status"):
        try:
            lines = status.read_text(encoding="utf-8").splitlines()
            ppid = int(next(line for line in lines if line.startswith("PPid:")).split()[1])
            pid = int(status.parent.name)
        except (FileNotFoundError, ProcessLookupError, StopIteration, ValueError):
            continue
        children.setdefault(ppid, set()).add(pid)
    found: set[int] = set()
    pending = list(children.get(root_pid, ()))
    while pending:
        pid = pending.pop()
        if pid in found:
            continue
        found.add(pid)
        pending.extend(children.get(pid, ()))
    return found


def _signal_processes(pids: set[int], signum: signal.Signals) -> None:
    for pid in pids:
        with suppress(PermissionError, ProcessLookupError):
            os.kill(pid, signum)


def _reap_children() -> None:
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            return


def _terminate_descendants() -> None:
    descendants = _descendant_pids(os.getpid())
    _signal_processes(descendants, signal.SIGTERM)
    deadline = time.monotonic() + 2
    while descendants and time.monotonic() < deadline:
        _reap_children()
        time.sleep(0.02)
        descendants = _descendant_pids(os.getpid())
    _signal_processes(descendants, signal.SIGKILL)
    _reap_children()


def _run_bounded(
    command: Sequence[str], worktree: Path, log: IO[bytes], timeout_seconds: int
) -> int:
    _become_child_subreaper()
    process = subprocess.Popen(
        list(command),
        cwd=worktree,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        return_code = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        return_code = TIMEOUT_EXIT
    _terminate_descendants()
    return return_code


def _execute_in_worktree(
    repository: Path,
    worktree: Path,
    source_sha: str,
    command: Sequence[str],
    timeout_seconds: int,
    log_path: Path,
) -> int:
    _git(repository, "worktree", "add", "--detach", "--quiet", str(worktree), source_sha)
    try:
        if _git(worktree, "status", "--porcelain"):
            raise RuntimeError("disposable worktree is dirty before agent execution")
        _provision_interpreter(repository, worktree)
        if _git(worktree, "status", "--porcelain"):
            raise RuntimeError("dependency provisioning dirtied the disposable worktree")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("wb") as log:
            return _run_bounded(command, worktree, log, timeout_seconds)
    finally:
        _remove_worktree(repository, worktree)


def run_isolated(
    *,
    repository: Path,
    name: str,
    command: Sequence[str],
    timeout_seconds: int,
    state_dir: Path,
) -> int:
    repository = repository.resolve()
    started_ns = time.time_ns()
    log_path = state_dir / f"{name}-{started_ns}.log"
    receipt: dict[str, object] = {
        "name": name,
        "started_ns": started_ns,
        "timeout_seconds": timeout_seconds,
    }

    try:
        dirty = _git(repository, "status", "--porcelain", "--untracked-files=all")
        if dirty:
            raise DirtyRepository("source repository is dirty; routine would execute stale HEAD")
        source_sha = _git(repository, "rev-parse", "HEAD")
        receipt["source_sha"] = source_sha
        with (
            repository_lease(repository),
            tempfile.TemporaryDirectory(prefix=f"korpus-{name}-") as temporary,
        ):
            return_code = _execute_in_worktree(
                repository,
                Path(temporary) / "worktree",
                source_sha,
                command,
                timeout_seconds,
                log_path,
            )
    except RepositoryBusy as error:
        return_code = BUSY_EXIT
        receipt["reason"] = str(error)
    except DirtyRepository as error:
        return_code = DIRTY_EXIT
        receipt["reason"] = str(error)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        return_code = 1
        receipt["reason"] = f"{type(error).__name__}: {error}"

    receipt.update(
        {
            "finished_ns": time.time_ns(),
            "log": str(log_path),
            "return_code": return_code,
        }
    )
    _write_receipt(state_dir, name, receipt)
    return return_code


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--prompt-file", type=Path, required=True)
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--executable", default="claude")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.timeout_seconds < 1:
        raise SystemExit("--timeout-seconds must be positive")
    prompt = args.prompt_file.read_text(encoding="utf-8").strip()
    if not prompt:
        raise SystemExit("prompt file is empty")
    executable = shutil.which(args.executable)
    if executable is None:
        raise SystemExit(f"agent executable not found: {args.executable}")
    state_dir = args.state_dir or (
        Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "korpus-routines"
    )
    return run_isolated(
        repository=args.repository,
        name=args.name,
        command=[executable, "-p", prompt, "--output-format", "text"],
        timeout_seconds=args.timeout_seconds,
        state_dir=state_dir,
    )


if __name__ == "__main__":
    raise SystemExit(main())
