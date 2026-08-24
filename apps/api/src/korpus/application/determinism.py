"""Pure helpers for exact hash-seed determinism evidence."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from korpus.application.junit_contracts import junit_counts


def junit_contract(path: Path) -> dict[str, object]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite")); counts = junit_counts(root)
    outcomes: list[tuple[str, str, str]] = []
    for case in (case for suite in suites for case in suite.iter("testcase")):
        status = (
            "failure" if case.find("failure") is not None
            else "error" if case.find("error") is not None
            else "skipped" if case.find("skipped") is not None
            else "pass"
        )
        outcomes.append((case.attrib.get("classname", ""), case.attrib.get("name", ""), status))
    canonical = json.dumps(sorted(outcomes), ensure_ascii=False, separators=(",", ":"))
    return {**counts, "outcome_sha256": hashlib.sha256(canonical.encode()).hexdigest()}


def run_json(command: list[str], env: dict[str, str], root: Path, timeout: int) -> tuple[int, dict[str, object]]:
    proc = subprocess.run(command, cwd=root, env=env, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=timeout, check=False)
    if proc.returncode:
        return proc.returncode, {}
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return 1, {}
    return 0, payload if isinstance(payload, dict) else {}


def run_seed(seed: int, junit: Path, root: Path, tests: tuple[str, ...]) -> dict[str, object]:
    env = os.environ.copy()
    env.update(PYTHONHASHSEED=str(seed), PYTHONPATH=str(root / "apps/api/src"))
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--disable-warnings", f"--junitxml={junit}", *tests],
        cwd=root, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=120, check=False,
    )
    counts = junit_contract(junit) if junit.is_file() else {
        "tests": 0, "failures": 1, "errors": 1, "skipped": 0, "outcome_sha256": ""
    }
    replay_rc, replay = run_json(
        [sys.executable, "scripts/deterministic_replay_probe.py"], env, root, 30
    )
    return {"seed": seed, "exit_code": proc.returncode, "replay_exit_code": replay_rc,
            "semantic_replay_sha256": str(replay.get("sha256", "")), **counts}


def failures(runs: list[dict[str, object]], policy: dict[str, object]) -> list[str]:
    cardinality_ok = len({(r["tests"], r["skipped"]) for r in runs}) == 1
    failed = any(r["exit_code"] or r["replay_exit_code"] or r["failures"] or r["errors"] for r in runs)
    outcomes = {r["outcome_sha256"] for r in runs}
    replays = {r["semantic_replay_sha256"] for r in runs}
    checks = (
        (not policy.get("require_identical_test_cardinality") or cardinality_ok,
         "test cardinality differs across hash seeds"),
        (not policy.get("require_zero_failures") or not failed,
         "at least one deterministic seed run failed"),
        (len(outcomes) == 1 and "" not in outcomes, "exact test outcomes differ across hash seeds"),
        (len(replays) == 1 and "" not in replays, "semantic replay digest differs across hash seeds"),
    )
    return [message for passed, message in checks if not passed]
