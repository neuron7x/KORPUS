from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/aggregate_ci_security_summary.py"


def _marker(path: Path, commit: str, scanners: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps(
            {"schema": "korpus.ci-scanner-result.v1", "commit_sha": commit, "scanners": scanners}
        )
    )


def _run(tmp_path: Path, markers: list[Path], commit: str = "a" * 40):
    out = tmp_path / "summary.json"
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, markers), "--out", str(out)],
        cwd=ROOT,
        env={"CI_COMMIT_SHA": commit},
        capture_output=True,
        text=True,
        check=False,
    ), out


def test_exact_clean_scanner_set_passes(tmp_path: Path) -> None:
    commit = "a" * 40
    a, b, c = (tmp_path / name for name in ("a.json", "b.json", "c.json"))
    _marker(a, commit, [{"scanner": "gitleaks", "exit_code": 0}])
    _marker(
        b,
        commit,
        [
            {"scanner": "pip-audit:runtime", "exit_code": 0},
            {"scanner": "pip-audit:dev", "exit_code": 0},
        ],
    )
    _marker(c, commit, [{"scanner": "trivy", "exit_code": 0}])
    run, out = _run(tmp_path, [a, b, c], commit)
    assert run.returncode == 0
    assert json.loads(out.read_text())["status"] == "PASS"


def test_missing_nonzero_or_stale_marker_fails(tmp_path: Path) -> None:
    commit = "b" * 40
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    _marker(a, commit, [{"scanner": "gitleaks", "exit_code": 0}])
    _marker(
        b,
        "c" * 40,
        [
            {"scanner": "pip-audit:runtime", "exit_code": 1},
            {"scanner": "pip-audit:dev", "exit_code": 0},
        ],
    )
    run, out = _run(tmp_path, [a, b], commit)
    assert run.returncode != 0
    report = json.loads(out.read_text())
    assert report["status"] == "FAIL"
    assert {
        "scanner_set_exact",
        "all_scanners_zero",
        "single_commit",
        "current_commit",
    }.intersection(report["failures"])
