"""Three policies that had to be checked against the disk rather than written down.

INF-012, OPS-003, OPS-005 and SUP-008 were each a policy nobody had written, and the
temptation with all four is to write it and stop. A policy in a document is a sentence;
what makes it a control is something that looks at the disk and says which clause is
currently false.

The tests here are about the checkers refusing to be flattering:

  an external clause is reported as external, never as failed — a clause nothing on this
  host can satisfy, counted as a failure, trains everyone to read red as normal;
  a scan that never ran is UNSCANNED and exits 2, not a pass;
  a scanner that exited 127 was absent, which is neither clean nor a finding;
  with no KEV catalogue loaded every finding is `kev_unknown`, because assuming absence
  from a list nobody opened is the failure this project is about.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RETENTION = ROOT / "scripts/retention_policy.py"
PATCH = ROOT / "scripts/patch_policy.py"


def _run(tool: Path, arguments: list[str]) -> tuple[int, dict[str, object]]:
    completed = subprocess.run(
        [sys.executable, str(tool), *arguments],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
        env={**os.environ, "PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        timeout=300,
    )
    return completed.returncode, json.loads(completed.stdout or "{}")


def test_an_external_clause_is_not_counted_as_a_failure(tmp_path: Path) -> None:
    """Otherwise a permanently-red board is normal, which is the same as no board."""
    _, report = _run(
        RETENTION,
        [
            "--backup-dir", str(tmp_path / "backups"),
            "--offsite-dir", str(tmp_path / "offsite"),
            "--evidence-dir", str(tmp_path / "evidence"),
            "--out", str(tmp_path / "out.json"),
        ],
    )

    external = [
        clause
        for body in report["findings"].values()  # type: ignore[union-attr]
        for clause in body["clauses"]
        if clause["scope"] == "external"
    ]
    assert external, "no external clause: this test is asserting nothing"
    for clause in external:
        assert clause["met"] is None, clause["name"]


def test_a_missing_backup_is_reported_as_missing(tmp_path: Path) -> None:
    code, report = _run(
        RETENTION,
        [
            "--backup-dir", str(tmp_path / "backups"),
            "--offsite-dir", str(tmp_path / "offsite"),
            "--evidence-dir", str(tmp_path / "evidence"),
            "--out", str(tmp_path / "out.json"),
        ],
    )

    assert code != 0
    assert report["status"] == "FAIL"


def test_a_policy_run_where_nothing_was_scanned_is_not_a_pass(tmp_path: Path) -> None:
    """The control that matters most: silence is not evidence of health."""
    code, report = _run(
        PATCH,
        ["--reports", str(tmp_path / "security"), "--out", str(tmp_path / "patch.json")],
    )

    assert code == 2
    assert report["status"] == "UNSCANNED"
    assert report["status"] != "PASS"


def test_a_stale_scan_fails(tmp_path: Path) -> None:
    """The most common way a dependency policy fails is that the scan stopped running."""
    reports = tmp_path / "security"
    reports.mkdir()
    (reports / "summary.json").write_text(
        json.dumps(
            {
                "ran_at": (datetime.now(UTC) - timedelta(days=40)).isoformat(),
                "scanners": [{"scanner": "trivy", "exit_code": 0}],
            }
        ),
        encoding="utf-8",
    )

    code, report = _run(
        PATCH, ["--reports", str(reports), "--out", str(tmp_path / "patch.json")]
    )

    assert code != 0
    assert report["scan_is_stale"] is True


def test_a_scanner_that_never_started_fails_the_policy(tmp_path: Path) -> None:
    """127 is "the tool was absent", which is neither clean nor a finding."""
    reports = tmp_path / "security"
    reports.mkdir()
    (reports / "summary.json").write_text(
        json.dumps(
            {
                "ran_at": datetime.now(UTC).isoformat(),
                "scanners": [
                    {"scanner": "trivy", "exit_code": 0},
                    {"scanner": "gitleaks", "exit_code": 127},
                ],
            }
        ),
        encoding="utf-8",
    )

    code, report = _run(
        PATCH, ["--reports", str(reports), "--out", str(tmp_path / "patch.json")]
    )

    assert code != 0
    assert report["unexecuted_scanners"] == ["gitleaks"]


def test_without_a_kev_catalogue_findings_are_unknown_not_clean(tmp_path: Path) -> None:
    """Assuming absence from a list nobody opened is the failure this project is about."""
    reports = tmp_path / "security"
    reports.mkdir()
    (reports / "summary.json").write_text(
        json.dumps(
            {
                "ran_at": datetime.now(UTC).isoformat(),
                "scanners": [{"scanner": "t", "exit_code": 0}],
            }
        ),
        encoding="utf-8",
    )
    (reports / "trivy-fs.json").write_text(
        json.dumps(
            {
                "Results": [
                    {
                        "Vulnerabilities": [
                            {"VulnerabilityID": "CVE-2026-0001", "Severity": "LOW", "PkgName": "x"}
                        ]
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    _, report = _run(
        PATCH,
        [
            "--reports", str(reports),
            "--kev", str(tmp_path / "absent-kev.json"),
            "--out", str(tmp_path / "patch.json"),
        ],
    )

    assert report["kev_catalogue"]["state"] == "absent"  # type: ignore[index]
    assert report["findings"] == 1
