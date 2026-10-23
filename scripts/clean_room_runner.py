from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from clean_room_contract import junit_counts

TEST_ARGS = ("apps/api/tests",)


def pytest_environment(work: Path, python: Path) -> dict[str, str]:
    home = work.parent / "pytest-home"
    return {
        "HOME": str(home),
        "XDG_CACHE_HOME": str(home / "cache"),
        "PATH": f"{python.parent}:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONPATH": f"{work / 'apps/api/src'}:{work / 'scripts'}:{work}",
    }


def _collect(work: Path, python: Path, environment: dict[str, str]) -> list[str]:
    marker = "KORPUS_NODEIDS_JSON="
    collector = f"""import json, pytest, sys
class P:
    def pytest_collection_finish(self, session):
        print({marker!r} + json.dumps([item.nodeid for item in session.items], separators=(',', ':')))
sys.exit(pytest.main(['--rootdir', {str(work)!r}, '--collect-only', '-q', '-o', 'addopts=', *json.loads(sys.argv[1])], plugins=[P()]))
"""
    completed = subprocess.run(
        [str(python), "-c", collector, json.dumps(TEST_ARGS)],
        cwd=work,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    line = next((row for row in completed.stdout.splitlines() if row.startswith(marker)), "")
    try:
        raw = json.loads(line[len(marker) :]) if line else []
    except json.JSONDecodeError:
        raw = []
    nodeids = sorted(str(item) for item in raw) if isinstance(raw, list) else []
    if completed.returncode or not nodeids or len(nodeids) != len(set(nodeids)):
        raise RuntimeError(f"clean-room collection failed ({completed.returncode})")
    return nodeids


def collection_digest(nodeids: list[str]) -> str:
    return hashlib.sha256("\n".join(nodeids).encode("utf-8")).hexdigest()


def run_battery(work: Path, python: Path) -> tuple[int, dict[str, int], bytes, list[str]]:
    junit = work / "clean-room-junit.xml"
    environment = pytest_environment(work, python)
    nodeids = _collect(work, python, environment)
    completed = subprocess.run(
        [
            str(python),
            "-m",
            "pytest",
            *TEST_ARGS,
            "-q",
            "-o",
            "addopts=",
            "-p",
            "no:cacheprovider",
            f"--junitxml={junit}",
        ],
        cwd=work,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        print(completed.stdout[-4000:])
    return completed.returncode, junit_counts(junit), junit.read_bytes(), nodeids
